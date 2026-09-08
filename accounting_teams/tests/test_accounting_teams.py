# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountingTeams(TransactionCase):
    """يتحقق فعلياً من أن التقييد "يعضّ": محاسب عادي (غير مدير) لا يرى
    دفاتر الفرق الأخرى ولا قيودها ولا بنودها، بينما مدير المحاسبة يرى كل
    شيء - ولا تتأثر أي عملية تعمل بصلاحيات النظام (sudo)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Team = cls.env['account.team']
        cls.team_ar = Team.create({'name': 'فريق الذمم المدينة', 'company_id': cls.company.id})
        cls.team_ap = Team.create({'name': 'فريق الذمم الدائنة', 'company_id': cls.company.id})

        Journal = cls.env['account.journal']
        cls.journal_sale = Journal.create({
            'name': 'مبيعات - اختبار', 'code': 'TSAL', 'type': 'sale',
            'company_id': cls.company.id, 'team_ids': [(6, 0, cls.team_ar.ids)],
        })
        cls.journal_purchase = Journal.create({
            'name': 'مشتريات - اختبار', 'code': 'TPUR', 'type': 'purchase',
            'company_id': cls.company.id, 'team_ids': [(6, 0, cls.team_ap.ids)],
        })
        cls.journal_open = Journal.create({
            'name': 'عمليات متنوعة - اختبار', 'code': 'TMIS', 'type': 'general',
            'company_id': cls.company.id,
        })

        group_invoice = cls.env.ref('account.group_account_invoice')
        group_manager = cls.env.ref('account.group_account_manager')
        base_user = cls.env.ref('base.group_user')

        def _user(login, name, groups, teams):
            user = cls.env['res.users'].create({
                'name': name, 'login': login,
                'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
                'group_ids': [(6, 0, groups)],
            })
            if teams:
                teams.write({'member_ids': [(4, user.id)]})
            return user

        cls.accountant_ar = _user('test_team_ar', 'محاسب ذمم مدينة',
                                  [base_user.id, group_invoice.id], cls.team_ar)
        cls.accountant_ap = _user('test_team_ap', 'محاسب ذمم دائنة',
                                  [base_user.id, group_invoice.id], cls.team_ap)
        cls.accountant_none = _user('test_team_none', 'محاسب بلا فريق',
                                    [base_user.id, group_invoice.id], None)
        cls.manager = _user('test_team_manager', 'مدير المحاسبة',
                            [base_user.id, group_invoice.id, group_manager.id], None)

        cls.move_sale = cls._create_move(cls, cls.journal_sale)
        cls.move_purchase = cls._create_move(cls, cls.journal_purchase)
        cls.move_open = cls._create_move(cls, cls.journal_open)

    def _create_move(self, journal):
        return self.env['account.move'].create({
            'journal_id': journal.id,
            'move_type': 'entry',
            'company_id': journal.company_id.id,
        })

    # ------------------------------------------------------------------
    def _journals_visible_to(self, user):
        return self.env['account.journal'].with_user(user).search([
            ('id', 'in', (self.journal_sale + self.journal_purchase + self.journal_open).ids)
        ])

    def _moves_visible_to(self, user):
        return self.env['account.move'].with_user(user).search([
            ('id', 'in', (self.move_sale + self.move_purchase + self.move_open).ids)
        ])

    def test_accountant_sees_only_own_team_journals_plus_unassigned(self):
        visible = self._journals_visible_to(self.accountant_ar)
        self.assertIn(self.journal_sale, visible)
        self.assertIn(self.journal_open, visible, 'الدفتر بلا فريق يبقى مرئياً للجميع')
        self.assertNotIn(self.journal_purchase, visible)

    def test_other_team_accountant_sees_the_mirror_image(self):
        visible = self._journals_visible_to(self.accountant_ap)
        self.assertIn(self.journal_purchase, visible)
        self.assertIn(self.journal_open, visible)
        self.assertNotIn(self.journal_sale, visible)

    def test_accountant_without_team_sees_only_unassigned_journals(self):
        visible = self._journals_visible_to(self.accountant_none)
        self.assertEqual(visible, self.journal_open)

    def test_manager_sees_everything(self):
        journals = self._journals_visible_to(self.manager)
        self.assertIn(self.journal_sale, journals)
        self.assertIn(self.journal_purchase, journals)
        self.assertIn(self.journal_open, journals)
        moves = self._moves_visible_to(self.manager)
        self.assertEqual(len(moves), 3)

    def test_moves_follow_journal_access(self):
        visible = self._moves_visible_to(self.accountant_ar)
        self.assertIn(self.move_sale, visible)
        self.assertIn(self.move_open, visible)
        self.assertNotIn(self.move_purchase, visible)

    def test_move_lines_follow_journal_access(self):
        line = self.env['account.move.line'].with_user(self.accountant_ar).search([
            ('journal_id', '=', self.journal_purchase.id),
        ])
        self.assertFalse(line, 'بنود دفتر فريق آخر يجب ألا تظهر')

    def test_reading_forbidden_move_raises(self):
        with self.assertRaises(AccessError):
            self.move_purchase.with_user(self.accountant_ar).read(['name'])

    def test_sudo_automation_is_not_affected(self):
        """كل الأتمتة الداخلية (السداد البنكي، الدفعات المقدمة، رسوم
        التوظيف) تعمل بصلاحيات النظام - يجب ألا تتأثر بأي تقييد فرق."""
        moves = self.env['account.move'].with_user(self.accountant_ar).sudo().search([
            ('id', 'in', (self.move_sale + self.move_purchase + self.move_open).ids)
        ])
        self.assertEqual(len(moves), 3)

    def test_member_from_another_company_is_rejected(self):
        other_company = self.env['res.company'].create({'name': 'شركة أخرى - اختبار'})
        outsider = self.env['res.users'].create({
            'name': 'مستخدم شركة أخرى', 'login': 'test_team_outsider',
            'company_id': other_company.id, 'company_ids': [(6, 0, other_company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(ValidationError):
            self.team_ar.write({'member_ids': [(4, outsider.id)]})

    def test_duplicate_team_name_in_same_company_rejected(self):
        with self.assertRaises(Exception):
            self.env['account.team'].create({
                'name': 'فريق الذمم المدينة', 'company_id': self.company.id,
            })

    def test_journal_and_team_are_two_sides_of_one_relation(self):
        self.assertIn(self.journal_sale, self.team_ar.journal_ids)
        self.assertNotIn(self.journal_purchase, self.team_ar.journal_ids)
