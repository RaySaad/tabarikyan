# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeStatementSources(TransactionCase):
    """مصادر كشف حساب الموظف بعد الإصلاح.

    ثلاثة عيوب يغطيها هذا الملف: احتساب السجلات الملغاة، وقصر حساب
    الذمم على شركة واحدة، والسكوت حين لا يُعثر على الحساب."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف الكشف'})
        cls.reason = cls.env.ref('bank_settlement.advance_reason_salary_advance')

    def _advance(self, amount, state=False):
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': amount,
        })
        if state:
            # الحالة تُكتب بالمسار الداخلي: الكتابة المباشرة على state
            # يرفضها حارس السداد البنكي.
            advance._write_state({'state': state})
        return advance

    def _statement(self):
        return self.employee._get_employee_statement_data()

    # ------------------------------------------------------------------
    def test_active_advance_appears(self):
        """الضابط الموجب: لولاه لمرّ "لا يظهر شيء" على أنه نجاح."""
        self._advance(1500.0)
        lines = self._statement()['lines']
        self.assertTrue(
            any(line['debit'] == 1500.0 for line in lines),
            'السلفة القائمة لم تظهر في الكشف')

    def test_rejected_advance_is_excluded(self):
        self._advance(900.0, state='rejected')
        lines = self._statement()['lines']
        self.assertFalse(
            any(line['debit'] == 900.0 for line in lines),
            'سلفة مرفوضة ما زالت تُحتسب ديناً على الموظف')

    def test_cancelled_advance_is_excluded(self):
        self._advance(700.0, state='cancel')
        self.assertFalse(
            any(line['debit'] == 700.0 for line in self._statement()['lines']),
            'سلفة ملغاة ما زالت تُحتسب')

    # ------------------------------------------------------------------
    def test_warning_when_dues_account_is_missing(self):
        self.env.company.settlement_dues_account_code = 'XX-لا-يوجد'
        data = self._statement()
        self.assertTrue(data['warnings'],
                        'الكشف يخرج ناقصاً بلا تنبيه حين يغيب حساب الذمم')
        self.assertIn('XX-لا-يوجد', data['warnings'][0])

    def test_dues_account_code_comes_from_settings(self):
        """الرقم كان مثبَّتاً في الكود، والحساب الفعلي غيره."""
        self.assertEqual(
            self.env['res.company']._fields[
                'settlement_dues_account_code'].default(self.env.company),
            '211201')

    def test_dues_lines_are_collected_from_every_company(self):
        """لكل فرع حسابه بالرقم نفسه - أخذ الأول اعتباطاً يُسقط البقية."""
        code = 'ZZ9001'
        self.env.company.settlement_dues_account_code = code
        other_company = self.env['res.company'].create({'name': 'فرع الكشف'})
        partner = self.env['res.partner'].create({'name': 'جهة اتصال الكشف'})
        self.employee.sudo().work_contact_id = partner.id

        accounts = self.env['account.account']
        for company in (self.env.company, other_company):
            accounts |= self.env['account.account'].create({
                'name': 'ذمم %s' % company.name, 'code': code,
                'account_type': 'liability_payable', 'reconcile': True,
                'company_ids': [(6, 0, [company.id])],
            })
        self.assertEqual(len(accounts), 2, 'لم يُنشأ حسابان بالرقم نفسه')

        # البحث العادي يرى رقم الشركة الجارية وحدها (code محسوب من
        # حقل يعتمد على الشركة) - الضابط السالب الذي كشف العيب.
        naive = self.env['account.account'].sudo().search([('code', '=', code)])
        self.assertLess(len(naive), 2,
                        'افتراض الاختبار سقط: البحث العادي وجد الحسابين')

        found = self.employee._statement_dues_accounts(code)
        self.assertEqual(
            set(found.ids), set(accounts.ids),
            'جامع الحسابات لا يجد حساب كل فرع')
