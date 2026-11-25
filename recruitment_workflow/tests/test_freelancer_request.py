# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFreelancerRequest(TransactionCase):
    """مسار المتعاون المبسّط: خطوتان، بلا مرفقات ولا كفالة ولا عقد.

    الضابط الموجب في كل اختبار هو الطلب العادي: لولاه لمرّ "كل شيء
    متخطّى دائماً" على أنه نجاح."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.Request = cls.env['recruitment.request']
        cls.Stage = cls.env['recruitment.stage']

    def _request(self, freelancer=False, **extra):
        vals = {
            'employee_name': 'متعاون المسار' if freelancer else 'موظف المسار',
            # عشرة أرقام بالضبط (قيد _check_identification_id).
            'identification_id': '299887710' + ('1' if freelancer else '2'),
            'mobile': '0551112233',
            'email': 'freelancer.test@example.com',
            'is_freelancer': freelancer,
        }
        vals.update(extra)
        return self.Request.create(vals)

    def _codes_from(self, freelancer=False):
        """تسلسل المراحل الذي يسلكه الطلب فعلياً.

        على سجل غير محفوظ (new): المقصود قياس تسلسل _next_stage وحده،
        والكتابة الحقيقية للمرحلة تُشغّل قيود المرفقات والآثار الجانبية
        فتخلط ما نقيسه بما لا نقيسه (وهو ما يُختبَر في بقية الملف)."""
        stages = self.Stage.search([], order='sequence')
        request = self.Request.new({'is_freelancer': freelancer})
        request.stage_id = stages[0]
        codes = [request.stage_id.code]
        for _unused in range(12):
            nxt = request._next_stage()
            if not nxt:
                break
            codes.append(nxt.code)
            request.stage_id = nxt
        return codes

    # ------------------------------------------------------------------
    def test_freelancer_skips_sponsorship_and_approvals(self):
        codes = self._codes_from(freelancer=True)
        for skipped in ('project_review', 'gm_approval', 'paid',
                        'sponsorship_transfer', 'sponsorship_done',
                        'car_request'):
            self.assertNotIn(
                skipped, codes,
                'المتعاون مرّ بمرحلة %s وهي لا تنطبق عليه' % skipped)
        self.assertEqual(
            codes, ['new', 'operations_review', 'started'],
            'المسار المبسّط ليس خطوتين كما طُلب')

    def test_regular_request_still_walks_every_stage(self):
        """الضابط الموجب: الطلب العادي لم يتأثر."""
        codes = self._codes_from(freelancer=False)
        for required in ('project_review', 'gm_approval', 'paid',
                         'sponsorship_transfer', 'sponsorship_done',
                         'car_request'):
            self.assertIn(required, codes,
                          'الطلب العادي صار يتخطّى %s' % required)

    # ------------------------------------------------------------------
    def test_freelancer_moves_on_without_attachments(self):
        freelancer = self._request(freelancer=True)
        self.assertFalse(freelancer.attachments_complete,
                         'افتراض الاختبار سقط: المرفقات مكتملة أصلاً')
        freelancer.action_next_stage()
        self.assertEqual(freelancer.stage_id.code, 'operations_review',
                         'المتعاون عَلِق على المرفقات الإجبارية')

    def test_regular_request_is_still_blocked_by_attachments(self):
        """الضابط المقابل: إلزام المرفقات لم يُلغَ للجميع."""
        regular = self._request(freelancer=False)
        if regular.attachments_complete:
            self.skipTest('لا مرفقات إجبارية معرَّفة في هذه القاعدة')
        with self.assertRaises(UserError):
            regular.action_next_stage()

    def test_freelancer_needs_no_project(self):
        freelancer = self._request(freelancer=True)
        self.assertFalse(freelancer.project_id, 'افتراض الاختبار سقط')
        freelancer.action_next_stage()
        self.assertEqual(freelancer.stage_id.code, 'operations_review')

    # ------------------------------------------------------------------
    def test_approval_creates_the_employee_without_a_contract(self):
        freelancer = self._request(freelancer=True)
        freelancer.action_next_stage()   # new -> operations_review
        freelancer.action_next_stage()   # operations_review -> started
        self.assertEqual(freelancer.stage_id.code, 'started')
        self.assertEqual(freelancer.state, 'done')
        self.assertTrue(freelancer.employee_id,
                        'لم يُنشأ سجل الموظف للمتعاون')
        self.assertTrue(freelancer.employee_id.is_freelancer,
                        'سجل الموظف لم يُعلَّم كمتعاون')
        self.assertFalse(freelancer.contract_ref,
                         'أُنشئ عقد لمتعاون ليس على مسير الرواتب')

    def test_freelancer_employee_fills_the_advance_category(self):
        """الحلقة مكتملة: سلفة المتعاون تعرف نوعه بلا تذكُّر من المحاسب."""
        freelancer = self._request(freelancer=True)
        freelancer.action_next_stage()
        freelancer.action_next_stage()
        advance = self.env['bank.settlement.advance'].new({
            'employee_id': freelancer.employee_id.id,
        })
        advance._onchange_employee_id()
        self.assertEqual(advance.employee_category, 'freelancer')

    # ------------------------------------------------------------------
    def test_request_type_classifies_every_kind(self):
        """التصنيف الظاهر في القوائم يطابق العلَمين، لا يخالفهما."""
        self.assertEqual(self._request(freelancer=True).request_type,
                         'freelancer')
        self.assertEqual(self._request(freelancer=False).request_type,
                         'regular')
        imported = self._request(freelancer=False, identification_id='2998877103')
        imported.sudo().write({'is_import_request': True})
        self.assertEqual(imported.request_type, 'import',
                         'طلب الاستقدام لم يُصنَّف - التصنيف لا يتبع العلَم')

    def test_request_type_follows_the_flag_when_it_changes(self):
        """مخزَّن ومحسوب: التخزين بلا إعادة حساب يُجمِّد تصنيفاً خاطئاً."""
        request = self._request(freelancer=False)
        self.assertEqual(request.request_type, 'regular')
        request.is_freelancer = True
        self.assertEqual(request.request_type, 'freelancer')

    # ------------------------------------------------------------------
    def test_freelancer_is_refused_by_payroll(self):
        freelancer = self._request(freelancer=True)
        freelancer.action_next_stage()
        freelancer.action_next_stage()
        with self.assertRaises(UserError):
            freelancer.employee_id._check_payroll_eligible()

    def test_regular_employee_passes_payroll_check(self):
        """الضابط المقابل: الحارس لا يمنع الموظفين الرسميين."""
        employee = self.env['hr.employee'].create({'name': 'موظف رسمي للفحص'})
        self.assertFalse(employee.is_freelancer)
        employee._check_payroll_eligible()   # لا يرفع

    # ------------------------------------------------------------------
    def test_type_is_locked_after_leaving_the_first_stage(self):
        """تبديل النوع لاحقاً يبدّل المراحل المتخطّاة تحت قدمي الطلب."""
        freelancer = self._request(freelancer=True)
        freelancer.action_next_stage()
        with self.assertRaises(UserError):
            freelancer.is_freelancer = False
