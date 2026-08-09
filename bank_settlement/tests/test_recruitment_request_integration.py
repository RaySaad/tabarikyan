# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentRequestIntegration(TransactionCase):
    """يتحقق من الربط التلقائي بين طلب التوظيف (recruitment_workflow) وسجل
    "الرسوم الحكومية" في السداد البنكي (bank_settlement) عند إصدار فاتورة
    حصة الموظف من رسوم نقل الكفالة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['recruitment.request']
        cls.GovFee = cls.env['bank.settlement.government.fee']

    def _create_request(self, **kwargs):
        vals = {
            'employee_name': 'موظف تجريبي - سداد بنكي',
            'identification_id': '1234567830',
            'mobile': '0501234567',
            'email': 'bank.settlement.test@example.com',
            'gov_fee_amount': 1000.0,
            'gov_fee_employee_amount': 300.0,
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    def test_invoice_creates_linked_gov_fee_record(self):
        """إصدار فاتورة حصة الموظف يُنشئ فوراً سجل "رسوم حكومية" مرتبطاً
        بنفس المبالغ والفاتورة، بدون موظف رسمي بعد (لم تُنشأ hr.employee)."""
        request = self._create_request(identification_id='1234567831', email='bs1@example.com')

        request.action_create_gov_fee_employee_invoice()

        gov_fee = request.bank_settlement_gov_fee_id
        self.assertTrue(gov_fee)
        self.assertEqual(gov_fee.recruitment_request_id, request)
        self.assertEqual(gov_fee.fee_type, 'sponsorship_transfer')
        self.assertEqual(gov_fee.amount, 1000.0)
        self.assertEqual(gov_fee.employee_amount, 300.0)
        self.assertEqual(gov_fee.employee_move_id, request.gov_fee_employee_move_id)
        self.assertFalse(gov_fee.employee_id)

    def test_employee_backfilled_once_hr_employee_created(self):
        """بمجرد إنشاء سجل الموظف الرسمي (_create_employee، عند مباشرة
        العمل)، يُكمَل حقل "اسم الموظف" تلقائياً على سجل الرسوم الحكومية
        المرتبط - دون الحاجة لتدخل يدوي."""
        request = self._create_request(identification_id='1234567832', email='bs2@example.com')
        request.action_create_gov_fee_employee_invoice()
        gov_fee = request.bank_settlement_gov_fee_id
        self.assertFalse(gov_fee.employee_id)

        employee = request._create_employee()

        self.assertEqual(gov_fee.employee_id, employee)

    def test_no_gov_fee_record_created_without_invoice(self):
        """بدون إصدار الفاتورة، لا يُنشأ أي سجل رسوم حكومية تلقائياً."""
        request = self._create_request(identification_id='1234567833', email='bs3@example.com')
        self.assertFalse(request.bank_settlement_gov_fee_id)
