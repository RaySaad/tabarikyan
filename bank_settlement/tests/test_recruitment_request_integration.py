# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentRequestIntegration(TransactionCase):
    """يتحقق من الربط التلقائي بين طلب التوظيف (recruitment_workflow)
    وسجل "الرسوم الحكومية" في السداد البنكي (bank_settlement) عند تسجيل
    المبلغ الإجمالي لرسوم نقل الكفالة، وشرط مرحلة "تم السداد" المرتبط
    بحالة سداد المنصة الفعلية."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['recruitment.request']
        cls.GovFee = cls.env['bank.settlement.government.fee']
        cls.stage_sponsorship_transfer = cls.env.ref('recruitment_workflow.stage_sponsorship_transfer')
        cls.stage_paid = cls.env.ref('recruitment_workflow.stage_paid')

    def _create_request(self, **kwargs):
        vals = {
            'employee_name': 'موظف تجريبي - سداد بنكي',
            'identification_id': '1234567830',
            'mobile': '0501234567',
            'email': 'bank.settlement.test@example.com',
            'gov_fee_amount': 1000.0,
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    def test_registering_gov_fee_creates_linked_record(self):
        """تسجيل الرسوم الحكومية يُنشئ فوراً سجل "رسوم حكومية" مرتبطاً
        بنفس المبلغ، بدون موظف رسمي بعد (لم تُنشأ hr.employee)."""
        request = self._create_request(identification_id='1234567831', email='bs1@example.com')

        request.action_register_gov_fee()

        gov_fee = request.bank_settlement_gov_fee_id
        self.assertTrue(gov_fee)
        self.assertEqual(gov_fee.recruitment_request_id, request)
        self.assertEqual(gov_fee.fee_type, 'sponsorship_transfer')
        self.assertEqual(gov_fee.amount, 1000.0)
        self.assertFalse(gov_fee.employee_id)

    def test_employee_backfilled_once_hr_employee_created(self):
        """بمجرد إنشاء سجل الموظف الرسمي (_create_employee، عند مباشرة
        العمل)، يُكمَل حقل "اسم الموظف" تلقائياً على سجل الرسوم الحكومية
        المرتبط - دون الحاجة لتدخل يدوي."""
        request = self._create_request(identification_id='1234567832', email='bs2@example.com')
        request.action_register_gov_fee()
        gov_fee = request.bank_settlement_gov_fee_id
        self.assertFalse(gov_fee.employee_id)

        employee = request._create_employee()

        self.assertEqual(gov_fee.employee_id, employee)

    def test_no_gov_fee_record_created_without_registration(self):
        """بدون الضغط على زر تسجيل الرسوم الحكومية، لا يُنشأ أي سجل
        تلقائياً."""
        request = self._create_request(identification_id='1234567833', email='bs3@example.com')
        self.assertFalse(request.bank_settlement_gov_fee_id)

    def test_paid_stage_blocked_until_gov_fee_settlement_done(self):
        """مرحلة "تم السداد": لا يمكن مغادرتها حتى يصل سجل "الرسوم
        الحكومية" المرتبط لحالة "منفّذة" - تأكيداً لسداد المنصة/الجهة
        الحكومية فعلياً."""
        request = self._create_request(identification_id='1234567835', email='bs5@example.com')
        request.action_register_gov_fee()
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_paid.id,
        })

        with self.assertRaises(UserError):
            request.action_next_stage()

        gov_fee = request.bank_settlement_gov_fee_id
        gov_fee.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search([('company_id', '=', gov_fee.company_id.id)], limit=1).id,
        })
        gov_fee.action_submit_review()
        gov_fee.action_confirm()
        gov_fee.action_done()
        self.assertEqual(gov_fee.state, 'done')

        request.action_next_stage()
        self.assertEqual(request.stage_id.code, 'sponsorship_done')

    def test_paid_stage_free_without_gov_fee_amount(self):
        """بدون أي مبلغ رسوم حكومية على الطلب أصلاً، لا قيد على مغادرة
        مرحلة "تم السداد"."""
        request = self._create_request(
            identification_id='1234567836', email='bs6@example.com',
            gov_fee_amount=0.0,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_paid.id,
        })

        request.action_next_stage()
        self.assertEqual(request.stage_id.code, 'sponsorship_transfer')
