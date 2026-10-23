# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSectionGroups(TransactionCase):
    """فصل الأقسام: موظف القسم يرى قسمه وحده.

    لكل تأكيد ضابط مقابل: لا يكفي أن يفتح موظف السلف السلف، بل يجب أن
    تُرفض عليه الرسوم الحكومية - وإلا كان الفصل شكلياً."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.env.ref('base.group_user')

        def _user(login, group_xmlid):
            return cls.env['res.users'].create({
                'name': login, 'login': login,
                'group_ids': [(4, base.id), (4, cls.env.ref(group_xmlid).id)],
            })

        cls.advance_clerk = _user(
            'clerk_advance', 'bank_settlement.group_section_advance')
        cls.gov_clerk = _user(
            'clerk_gov', 'bank_settlement.group_section_government_fee')
        cls.accountant = _user(
            'settlement_accountant', 'bank_settlement.group_bank_settlement_reviewer')
        cls.plain_user = _user(
            'settlement_plain', 'bank_settlement.group_bank_settlement_user')

    # ------------------------------------------------------------------
    def test_advance_clerk_reads_only_advances(self):
        Advance = self.env['bank.settlement.advance'].with_user(self.advance_clerk)
        self.assertTrue(Advance.has_access('read'), 'موظف السلف لا يفتح السلف')
        Gov = self.env['bank.settlement.government.fee'].with_user(self.advance_clerk)
        self.assertFalse(Gov.has_access('read'),
                         'موظف السلف يرى الرسوم الحكومية - الفصل شكلي')
        with self.assertRaises(AccessError):
            Gov.search([])

    def test_government_clerk_reads_only_government_fees(self):
        Gov = self.env['bank.settlement.government.fee'].with_user(self.gov_clerk)
        self.assertTrue(Gov.has_access('read'))
        Advance = self.env['bank.settlement.advance'].with_user(self.gov_clerk)
        self.assertFalse(Advance.has_access('read'),
                         'موظف الرسوم يرى السلف')

    def test_base_user_alone_sees_no_section(self):
        """"مستخدم" وحدها صارت دخولاً للتطبيق لا مفتاحاً لكل الأقسام."""
        for model in ('bank.settlement.advance', 'bank.settlement.government.fee',
                      'bank.settlement.vehicle.transfer',
                      'bank.settlement.medical.insurance',
                      'bank.settlement.representative'):
            self.assertFalse(
                self.env[model].with_user(self.plain_user).has_access('read'),
                'مجموعة "مستخدم" وحدها ما زالت تفتح %s' % model)

    def test_accountant_still_sees_every_section(self):
        """المحاسب ينفّذ الصرف في كل الأقسام - تقييده يوقف العمل."""
        for model in ('bank.settlement.advance', 'bank.settlement.government.fee',
                      'bank.settlement.vehicle.transfer',
                      'bank.settlement.medical.insurance',
                      'bank.settlement.representative'):
            self.assertTrue(
                self.env[model].with_user(self.accountant).has_access('read'),
                'المحاسب فقد قسم %s' % model)

    # ------------------------------------------------------------------
    def test_home_tiles_follow_the_user_groups(self):
        """الأيقونات تُبنى من الصلاحية نفسها لا من قائمة ثابتة."""
        Dashboard = self.env['bank.settlement.dashboard']
        data = Dashboard.with_user(self.advance_clerk).get_sections()
        keys = [section['key'] for section in data['sections']]
        self.assertEqual(keys, ['advance'],
                         'بطاقات موظف السلف ليست بطاقة واحدة: %s' % keys)
        self.assertFalse(
            [extra for extra in data['extras'] if extra['key'] == 'overview'],
            'بطاقة اللوحة الشاملة ظهرت لمن لا يرى كل الأقسام')

        accountant_data = Dashboard.with_user(self.accountant).get_sections()
        self.assertEqual(len(accountant_data['sections']), 5,
                         'المحاسب لا يرى الأقسام الخمسة')
        self.assertTrue(
            [extra for extra in accountant_data['extras'] if extra['key'] == 'overview'],
            'اللوحة الشاملة غائبة عمّن يرى كل الأقسام')

    def test_section_dashboard_refuses_a_foreign_section(self):
        """الرابط المباشر لا يتجاوز الصلاحية."""
        with self.assertRaises(AccessError):
            self.env['bank.settlement.dashboard'].with_user(
                self.advance_clerk).get_section_data('government_fee')
