# -*- coding: utf-8 -*-
"""ثغرات تجاوز مُثبتة بفحص مباشر على قاعدة اختبار - مغلقة الآن.

كانت حراس الحالة والحقول المقفولة تُرفع بمفتاح في السياق، والسياق يصل
من العميل مع كل نداء RPC؛ فكان أي مستخدم يملك صلاحية الكتابة قادراً
على تمريره وتخطّي سلسلة الاعتماد كاملةً.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRpcBypass(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'مستخدم سداد عادي', 'login': 'bypass_probe_user',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('bank_settlement.group_bank_settlement_user').id,
            ])],
        })
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف فحص التجاوز'})
        cls.reason = cls.env.ref('bank_settlement.advance_reason_salary_advance')

    def _advance(self):
        return self.env['bank.settlement.advance'].with_user(self.user).create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': 100.0,
            'payment_method': 'stc_pay',
            'stc_number': '0501234567',
        })

    # ---- تغيير الحالة مباشرة ----
    def test_user_cannot_jump_an_advance_to_paid(self):
        """كان يمر: سلفة "تم الصرف" بلا موافقة مسؤول المشروع ولا اعتماد
        المدير العام، وتظهر في كشف حساب الموظف."""
        advance = self._advance()
        with self.assertRaises(UserError):
            advance.write({'state': 'paid'})
        self.assertEqual(advance.state, 'draft')

    def test_user_cannot_jump_a_government_fee_to_done(self):
        Entity = self.env['bank.settlement.government.entity']
        FeeType = self.env['bank.settlement.government.fee.type']
        entity = Entity.search([], limit=1) or Entity.sudo().create(
            {'name': 'جهة فحص التجاوز'})
        fee_type = FeeType.search([], limit=1) or FeeType.sudo().create(
            {'name': 'نوع رسوم فحص التجاوز'})
        fee = self.env['bank.settlement.government.fee'].with_user(self.user).create({
            'employee_id': self.employee.id, 'amount': 100.0,
            'government_entity_id': entity.id, 'fee_type_id': fee_type.id,
        })
        with self.assertRaises(UserError):
            fee.write({'state': 'done'})
        self.assertEqual(fee.state, 'draft')

    def test_records_cannot_be_born_already_approved(self):
        """إغلاق الباب الآخر: الإنشاء مباشرةً في حالة متقدّمة."""
        with self.assertRaises(UserError):
            self.env['bank.settlement.advance'].with_user(self.user).create({
                'employee_id': self.employee.id,
                'advance_reason_id': self.reason.id, 'amount': 100.0,
                'payment_method': 'stc_pay', 'stc_number': '0501234567',
                'state': 'approved',
            })

    # ---- تجاوز قفل الحقول بالسياق ----
    def test_context_flag_from_a_client_cannot_unlock_approved_fields(self):
        """كان يمر: تعديل مبلغ سلفة بعد اعتماد المدير العام إلى 99999."""
        advance = self._advance()
        advance.sudo()._write_state({'state': 'approved'})

        with self.assertRaises(UserError):
            advance.with_context(
                bank_settlement_skip_approval_lock=True,
            ).write({'amount': 99999.0})
        self.assertEqual(advance.amount, 100.0)

    def test_context_flag_cannot_force_a_state_change(self):
        advance = self._advance()
        with self.assertRaises(UserError):
            advance.with_context(
                bank_settlement_state_write=True,
            ).write({'state': 'paid'})

    # ---- المسار الصحيح ما زال يعمل ----
    def test_the_normal_button_path_still_moves_the_state(self):
        advance = self._advance()
        advance.action_submit_review()
        self.assertEqual(advance.state, 'waiting_approval')
