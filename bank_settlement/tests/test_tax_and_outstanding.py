# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSettlementTaxAndOutstanding(TransactionCase):
    """انعكاس الضريبة في الفاتورة، وقيد الصرف على المدفوعات المعلقة.

    العيبان كما ظهرا في بيانات حقيقية: فاتورة تأمين بإجمالي 103.27 بلا
    سطر ضريبة، وقيد سلفة يُنقص رصيد البنك قبل ظهوره في كشف البنك."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # مجموعة الضريبة إلزامية في أودو 19 - تُعاد المستعملة إن وُجدت.
        tax_group = cls.env['account.tax.group'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if not tax_group:
            tax_group = cls.env['account.tax.group'].create({
                'name': 'ضريبة القيمة المضافة (اختبار)',
                'company_id': cls.company.id,
            })
        cls.tax = cls.env['account.tax'].create({
            'name': 'ضريبة مشتريات 15% (اختبار)',
            'type_tax_use': 'purchase',
            'amount_type': 'percent',
            'amount': 15.0,
            'tax_group_id': tax_group.id,
            'company_id': cls.company.id,
        })
        cls.company.account_purchase_tax_id = cls.tax.id

        cls.employee = cls.env['hr.employee'].create({'name': 'موظف الضريبة'})
        cls.vendor = cls.env['res.partner'].create({'name': 'التعاونية (اختبار)'})
        cls.insurance_type = cls.env['bank.settlement.medical.insurance.type'].search(
            [], limit=1)
        cls.expense_account = cls.env['account.account'].create({
            'name': 'تأمين طبي (اختبار)', 'code': 'EXP512006',
            'account_type': 'expense',
            'company_ids': [(6, 0, [cls.company.id])],
        })
        cls.bank_journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)

    # ------------------------------------------------------------------
    def _insurance(self, amount=89.80):
        return self.env['bank.settlement.medical.insurance'].create({
            'employee_id': self.employee.id,
            'vendor_id': self.vendor.id,
            'fee_type_id': self.insurance_type.id,
            'linked_account_id': self.expense_account.id,
            'amount': amount,
        })

    def test_tax_amount_is_computed_from_company_tax(self):
        record = self._insurance()
        self.assertAlmostEqual(
            record.tax_amount, 13.47, places=2,
            msg='مبلغ الضريبة لم يُحسب من ضريبة المشتريات الافتراضية')
        self.assertAlmostEqual(record.total_amount, 103.27, places=2)

    def test_bill_line_carries_net_amount_and_tax(self):
        """الضريبة كانت تذوب في حساب المصروف - هذا هو جوهر العيب."""
        record = self._insurance()
        vals = record._get_settlement_bill_vals()
        line = vals['invoice_line_ids'][0][2]
        self.assertAlmostEqual(
            line['price_unit'], 89.80, places=2,
            msg='سطر الفاتورة ما زال يحمل الإجمالي بدل المبلغ الصافي')
        self.assertEqual(
            line['tax_ids'], [(6, 0, self.tax.ids)],
            'سطر الفاتورة بلا ضريبة')

    def test_exempt_record_keeps_gross_line_without_tax(self):
        """الضابط المقابل: رسوم معفاة يصفّر المحاسب ضريبتها."""
        record = self._insurance()
        record.tax_amount = 0.0
        vals = record._get_settlement_bill_vals()
        line = vals['invoice_line_ids'][0][2]
        self.assertAlmostEqual(line['price_unit'], 89.80, places=2)
        self.assertEqual(line['tax_ids'], [(5, 0, 0)],
                         'فُرضت ضريبة على سجل صفّر المحاسب ضريبته')

    def test_advance_carries_no_tax(self):
        """السلفة قرض للموظف لا شراء من مورد - تعميم ضريبة المشتريات
        عليها كان يضخّم 1000 إلى 1150 ويقيّد الفارق ذمةً عليه."""
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 1000.0,
        })
        self.assertEqual(advance.tax_amount, 0.0,
                         'فُرضت ضريبة مشتريات على سلفة موظف')
        self.assertEqual(advance.total_amount, 1000.0,
                         'مبلغ السلفة المقيَّد على الموظف أكبر مما صُرف له')

    def test_representative_settlement_carries_no_tax(self):
        self.assertFalse(
            self.env['bank.settlement.representative']._get_settlement_taxes
            and self.env['bank.settlement.representative'].new(
                {'employee_id': self.employee.id})._get_settlement_taxes(),
            'فُرضت ضريبة مشتريات على تصفية مندوب')

    # ------------------------------------------------------------------
    def test_direct_settlement_credits_outstanding_not_bank(self):
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 500.0,
            'journal_id': self.bank_journal.id,
        })
        # قاعدة الاختبار قد تكون بلا شجرة حسابات (ولا حساب معلّق فيها
        # أصلاً - حتى أودو نفسها تفشل حينها)، فنضبط حساباً صراحةً
        # ليقيس الاختبار سلوكنا لا نقص القاعدة.
        outstanding_account = self.env['account.account'].create({
            'name': 'مدفوعات معلقة (اختبار)', 'code': 'OUT999',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [(6, 0, [self.company.id])],
        })
        # أعلى مصدر في الترتيب (طريقة الدفع الصادرة على الدفتر) - انظر
        # نفس الشرح في test_advance_repayment: الاكتفاء بحساب التحويلات
        # يجعل الاختبار يمر بلا شجرة حسابات ويفشل بوجودها.
        self.company.transfer_account_id = outstanding_account.id
        for line in self.bank_journal.outbound_payment_method_line_ids:
            line.payment_account_id = outstanding_account.id

        outstanding = advance._get_outstanding_payment_account()
        self.assertEqual(outstanding, outstanding_account,
                         'لم يُؤخذ حساب المدفوعات المعلقة المضبوط')
        self.assertNotEqual(
            outstanding, self.bank_journal.default_account_id,
            'حساب المعلّق هو حساب البنك نفسه - لا فائدة من التغيير')

        vals = advance._get_settlement_move_vals()
        credit_line = [line[2] for line in vals['line_ids']
                       if line[2]['credit']][0]
        self.assertEqual(
            credit_line['account_id'], outstanding.id,
            'الدائن ما زال على حساب البنك مباشرة')
        self.assertNotEqual(
            credit_line['account_id'],
            self.bank_journal.default_account_id.id,
            'رصيد البنك يُخصم قبل ظهور الحركة في كشف البنك')

    def test_missing_outstanding_falls_back_but_says_so(self):
        """بلا حساب معلّق: لا يتوقف العمل، ولا يسكت النظام.

        تُغلَق المصادر الثلاثة صراحةً (طريقة الدفع، شجرة الحسابات، حساب
        التحويلات) - وإلا كانت "القاعدة بلا شجرة حسابات" هي ما يصنع
        الحالة، فيختلف الاختبار باختلاف القاعدة."""
        self.company.transfer_account_id = False
        for line in self.bank_journal.outbound_payment_method_line_ids:
            line.payment_account_id = False
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
            'journal_id': self.bank_journal.id,
        })
        before = len(advance.message_ids)
        ChartTemplate = type(self.env['account.chart.template'])
        with patch.object(ChartTemplate, 'ref', return_value=False):
            account = advance._get_outstanding_payment_account()
        self.assertEqual(account, self.bank_journal.default_account_id,
                         'لم يرجع إلى حساب البنك عند غياب المعلّق')
        self.assertGreater(len(advance.message_ids), before,
                           'رجع إلى حساب البنك بصمت بلا إشعار في السجل')
