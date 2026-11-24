# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFreelancerAdvance(TransactionCase):
    """سلفة متعاون (فريلانسر): نفس الشاشة ونفس سلسلة الاعتماد، ويتميّز
    بنوع الموظف وبالحساب المرتبط الذي يختاره المحاسب.

    لا يمرّ بمسير الرواتب: استرداد سلفته يكون بخصمها من مستحقاته عن
    عمله، فلا يصحّ أن يُقيَّد على حساب الموظفين نفسه بلا قرار محاسبي."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.company = cls.env.company
        cls.reason = cls.env.ref('bank_settlement.advance_reason_salary_advance')
        cls.freelancer = cls.env['hr.employee'].create({'name': 'متعاون تجريبي'})
        cls.contractor_account = cls.env['account.account'].create({
            'name': 'مستحقات متعاونين (اختبار)', 'code': 'FRL201500',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.journal:
            # قاعدة بلا شجرة حسابات لا دفتر بنكي فيها - يُنشأ هنا بدل
            # أن يفشل الاختبار لنقص في القاعدة لا في الكود.
            cls.journal = cls.env['account.journal'].create({
                'name': 'بنك المتعاونين', 'code': 'FRLB', 'type': 'bank',
                'company_id': cls.company.id,
            })

    def test_freelancer_category_exists(self):
        selection = dict(
            self.env['bank.settlement.advance']._fields[
                'employee_category'].selection)
        self.assertIn('freelancer', selection,
                      'لا يوجد نوع "متعاون" لتمييز الفريلانسر')
        self.assertIn('متعاون', selection['freelancer'])

    def test_freelancer_advance_runs_the_same_chain(self):
        """نفس السلسلة: مسودة ← مسؤول المشروع ← المدير العام ← الصرف."""
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.freelancer.id,
            'advance_reason_id': self.reason.id,
            'employee_category': 'freelancer',
            'amount': 1200.0,
            'payment_method': 'stc_pay', 'stc_number': '0501234567',
        })
        self.assertEqual(advance.employee_category, 'freelancer')
        advance.action_submit_review()
        self.assertEqual(advance.state, 'waiting_approval')
        advance.action_pm_approve()
        advance.action_confirm()
        advance.write({
            'journal_id': self.journal.id,
            # حساب المتعاونين لا حساب الموظفين: المحاسب يختاره صراحةً.
            'linked_account_id': self.contractor_account.id,
        })
        advance.action_done()
        self.assertEqual(advance.state, 'paid')

        debit = advance.move_id.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(
            debit.account_id, self.contractor_account,
            'سلفة المتعاون قُيِّدت على حساب غير الذي اختاره المحاسب')
        self.assertEqual(debit.debit, 1200.0)

    def test_freelancer_advance_can_be_split(self):
        """الصرف على دفعات يعمل للمتعاون كما للموظف."""
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.freelancer.id,
            'advance_reason_id': self.reason.id,
            'employee_category': 'freelancer',
            'amount': 1000.0,
            'payment_method': 'stc_pay', 'stc_number': '0501234567',
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        advance.action_confirm()
        advance.write({
            'journal_id': self.journal.id,
            'linked_account_id': self.contractor_account.id,
        })
        advance.action_disburse(400.0)
        self.assertEqual(advance.state, 'approved')
        self.assertEqual(advance.undisbursed_amount, 600.0)
        advance.action_disburse(600.0)
        self.assertEqual(advance.state, 'paid')
        self.assertEqual(advance.disbursement_count, 2)
