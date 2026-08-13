# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSettlementMixin(TransactionCase):
    """يتحقق من قفل الحقول المالية بعد إنشاء القيد المحاسبي، ومن اشتقاق
    الشركة من فرع الموظف المختار تلقائياً."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.GovFee = cls.env['bank.settlement.government.fee']
        cls.Representative = cls.env['bank.settlement.representative']

    def _create_gov_fee(self):
        return self.GovFee.create({
            'government_entity': 'mol_resident',
            'fee_type': 'sponsorship_transfer',
            'amount': 500.0,
        })

    def _complete_to_done(self, rec):
        rec.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', rec.company_id.id)], limit=1).id,
        })
        rec.action_submit_review()
        rec.action_confirm()
        rec.action_done()

    def test_amount_locked_after_move_created(self):
        gov_fee = self._create_gov_fee()
        self._complete_to_done(gov_fee)
        self.assertTrue(gov_fee.move_id)

        with self.assertRaises(UserError):
            gov_fee.write({'amount': 999.0})
        with self.assertRaises(UserError):
            gov_fee.write({'journal_id': self.env['account.journal'].search(
                [('id', '!=', gov_fee.journal_id.id)], limit=1).id})

    def test_amount_editable_before_move_created(self):
        gov_fee = self._create_gov_fee()
        gov_fee.write({'amount': 750.0})
        self.assertEqual(gov_fee.amount, 750.0)

    def test_representative_settlement_amount_locked_after_move(self):
        """settlement_amount هو الاسم البديل لـ amount في هذا النموذج -
        يجب أن يُقفل هو أيضاً، وليس فقط amount مباشرة."""
        rep = self.Representative.create({'settlement_amount': 400.0})
        self._complete_to_done(rep)

        with self.assertRaises(UserError):
            rep.write({'settlement_amount': 999.0})

    def test_company_derived_from_employee_branch(self):
        """اختيار موظف تابع لفرع معيّن يُحدّث شركة السجل تلقائياً لتطابق
        فرعه - بدل بقائها على الشركة الافتراضية للجلسة."""
        branch = self.env['res.company'].create({
            'name': 'فرع تجريبي - سداد بنكي', 'parent_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'موظف فرع تجريبي', 'company_id': branch.id,
        })
        gov_fee = self._create_gov_fee()
        self.assertNotEqual(gov_fee.company_id, branch)

        gov_fee.employee_id = employee
        gov_fee._onchange_employee_id()

        self.assertEqual(gov_fee.company_id, branch)
