# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentRequestIntegration(TransactionCase):
    """يتحقق من الربط التلقائي بين طلب التوظيف (recruitment_workflow)
    وسجلات السداد البنكي (bank_settlement) المرتبطة برسوم نقل الكفالة
    الحكومية: سجل "الرسوم الحكومية"، وسجل "سلفة" الموظف عند اختيار هذه
    الطريقة، وشرط مرحلة "تم السداد" الجديد المرتبط بحالة سداد المنصة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['recruitment.request']
        cls.GovFee = cls.env['bank.settlement.government.fee']
        cls.Advance = cls.env['bank.settlement.advance']
        cls.stage_sponsorship_transfer = cls.env.ref('recruitment_workflow.stage_sponsorship_transfer')
        cls.stage_paid = cls.env.ref('recruitment_workflow.stage_paid')

    def _create_request(self, **kwargs):
        vals = {
            'employee_name': 'موظف تجريبي - سداد بنكي',
            'identification_id': '1234567830',
            'mobile': '0501234567',
            'email': 'bank.settlement.test@example.com',
            'gov_fee_amount': 1000.0,
            'gov_fee_employee_amount': 300.0,
            'gov_fee_employee_payment_method': 'cash',
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    def test_invoice_creates_linked_gov_fee_record(self):
        """تسجيل الرسوم الحكومية (سداد نقدي لحصة الموظف) يُنشئ فوراً سجل
        "رسوم حكومية" مرتبطاً بنفس المبالغ والفاتورة، بدون موظف رسمي بعد
        (لم تُنشأ hr.employee)."""
        request = self._create_request(identification_id='1234567831', email='bs1@example.com')

        request.action_create_gov_fee_employee_invoice()

        gov_fee = request.bank_settlement_gov_fee_id
        self.assertTrue(gov_fee)
        self.assertEqual(gov_fee.recruitment_request_id, request)
        self.assertEqual(gov_fee.fee_type, 'sponsorship_transfer')
        self.assertEqual(gov_fee.amount, 1000.0)
        self.assertEqual(gov_fee.employee_amount, 300.0)
        self.assertEqual(gov_fee.employee_move_id, request.gov_fee_employee_move_id)
        self.assertTrue(gov_fee.employee_move_id)
        self.assertFalse(gov_fee.employee_id)
        self.assertFalse(request.bank_settlement_advance_id)

    def test_advance_method_creates_linked_advance_record_not_invoice(self):
        """اختيار "سلفة" لحصة الموظف يُنشئ سجل سلفة في السداد البنكي بدل
        فاتورة عميل - لا فاتورة (gov_fee_employee_move_id) في هذه الحالة."""
        request = self._create_request(
            identification_id='1234567834', email='bs4@example.com',
            gov_fee_employee_payment_method='advance',
        )

        request.action_create_gov_fee_employee_invoice()

        advance = request.bank_settlement_advance_id
        self.assertTrue(advance)
        self.assertEqual(advance.recruitment_request_id, request)
        self.assertEqual(advance.advance_reason, 'salary_advance')
        self.assertEqual(advance.amount, 300.0)
        self.assertFalse(advance.employee_id)
        self.assertFalse(request.gov_fee_employee_move_id)
        # سجل الرسوم الحكومية يُنشأ أيضاً بغض النظر عن طريقة سداد الموظف
        self.assertTrue(request.bank_settlement_gov_fee_id)

    def test_advance_method_no_invoice_created_even_after_gov_fee_done(self):
        """اكتمال سجل "الرسوم الحكومية" (منفّذة) لا يجب أن يُصدر فاتورة
        عميل لحصة الموظف عند اختيار "سلفة" - كان هذا خللاً موروثاً في
        action_done() يتجاهل طريقة السداد المختارة من طلب التوظيف."""
        request = self._create_request(
            identification_id='1234567837', email='bs7@example.com',
            gov_fee_employee_payment_method='advance',
        )
        request.action_create_gov_fee_employee_invoice()
        gov_fee = request.bank_settlement_gov_fee_id

        gov_fee.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', gov_fee.company_id.id)], limit=1).id,
        })
        gov_fee.action_submit_review()
        gov_fee.action_confirm()
        gov_fee.action_done()

        self.assertEqual(gov_fee.state, 'done')
        self.assertFalse(gov_fee.employee_move_id)
        self.assertFalse(request.gov_fee_employee_move_id)
        self.assertTrue(request.bank_settlement_advance_id)

    def test_employee_backfilled_once_hr_employee_created(self):
        """بمجرد إنشاء سجل الموظف الرسمي (_create_employee، عند مباشرة
        العمل)، تُكمَل حقول "اسم الموظف" تلقائياً على سجلي الرسوم
        الحكومية والسلفة المرتبطين - دون الحاجة لتدخل يدوي."""
        request = self._create_request(
            identification_id='1234567832', email='bs2@example.com',
            gov_fee_employee_payment_method='advance',
        )
        request.action_create_gov_fee_employee_invoice()
        gov_fee = request.bank_settlement_gov_fee_id
        advance = request.bank_settlement_advance_id
        self.assertFalse(gov_fee.employee_id)
        self.assertFalse(advance.employee_id)

        employee = request._create_employee()

        self.assertEqual(gov_fee.employee_id, employee)
        self.assertEqual(advance.employee_id, employee)

    def test_no_gov_fee_record_created_without_registration(self):
        """بدون الضغط على زر تسجيل الرسوم الحكومية، لا يُنشأ أي سجل
        تلقائياً."""
        request = self._create_request(identification_id='1234567833', email='bs3@example.com')
        self.assertFalse(request.bank_settlement_gov_fee_id)
        self.assertFalse(request.bank_settlement_advance_id)

    def test_paid_stage_blocked_until_gov_fee_settlement_done(self):
        """مرحلة "تم السداد": لا يمكن مغادرتها حتى يصل سجل "الرسوم
        الحكومية" المرتبط لحالة "منفّذة" - تأكيداً لسداد المنصة/الجهة
        الحكومية فعلياً، بغض النظر عن حالة حصة الموظف."""
        request = self._create_request(identification_id='1234567835', email='bs5@example.com')
        request.action_create_gov_fee_employee_invoice()
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
            gov_fee_amount=0.0, gov_fee_employee_amount=0.0,
            gov_fee_employee_payment_method=False,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_paid.id,
        })

        request.action_next_stage()
        self.assertEqual(request.stage_id.code, 'sponsorship_transfer')
