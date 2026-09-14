# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentDirectApproval(TransactionCase):
    """الاعتماد المباشر من الإدارة للطلبات الطائرة: يتخطى *مَن* يعتمد
    (بما فيه قاعدة مسؤول المشروع المعيّن تحديداً) - لا *ما* يُشترط."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['recruitment.request']
        cls.stage_project_review = cls.env.ref('recruitment_workflow.stage_project_review')
        cls.stage_paid = cls.env.ref('recruitment_workflow.stage_paid')
        base = cls.env.ref('base.group_user')
        rw_user = cls.env.ref('recruitment_workflow.group_recruitment_workflow_user')
        override = cls.env.ref('recruitment_workflow.group_approval_override')

        def user(login, groups):
            return cls.env['res.users'].create({
                'name': login, 'login': login, 'email': '%s@example.com' % login,
                'group_ids': [(6, 0, [g.id for g in groups])],
            })

        cls.assigned_pm = user('da_assigned_pm', [
            base, cls.env.ref('recruitment_workflow.group_recruitment_workflow_project_manager')])
        cls.override_user = user('da_override', [base, rw_user, override])
        cls.gm_user = user('da_gm', [
            base, cls.env.ref('recruitment_workflow.group_recruitment_workflow_gm')])
        cls.project = cls.env['project.project'].create({
            'name': 'منصة اعتماد مباشر', 'user_id': cls.assigned_pm.id,
        })

    def _request_at_project_review(self, identification_id='1234567801'):
        request = self.Request.create({
            'employee_name': 'مرشّح طائر',
            'identification_id': identification_id,
            'mobile': '0501234567',
            'email': 'flying_%s@example.com' % identification_id,
            'project_id': self.project.id,
        })
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })
        self.assertEqual(request.project_manager_id, self.assigned_pm)
        return request

    def test_override_user_jumps_all_approval_stages(self):
        """الاختناق الحقيقي: قاعدة "مسؤول المشروع المعيّن تحديداً" كانت
        تمنع حتى المدير العام. صاحب التجاوز - وهو ليس ذلك المسؤول - يعبر
        كل مراحل الاعتماد ويتوقف عند أول مرحلة تنفيذية."""
        request = self._request_at_project_review()
        request.with_user(self.override_user).action_direct_approve(reason='منصة بحاجة عاجلة')

        self.assertEqual(request.stage_id, self.stage_paid,
                         'لم يتوقف عند أول مرحلة تنفيذية ("تم السداد")')
        self.assertEqual(request.direct_approval_user_id, self.override_user)
        self.assertTrue(request.direct_approval_date)
        self.assertEqual(request.direct_approval_reason, 'منصة بحاجة عاجلة')
        log = request.message_ids.filtered(lambda m: 'اعتماد مباشر من الإدارة' in (m.body or ''))
        self.assertTrue(log, 'لم يُسجَّل الاعتماد المباشر في سجل الطلب')

    def test_general_manager_without_the_group_cannot(self):
        """مجموعة مستقلة تُمنح بالاسم: المدير العام لا يملكها تلقائياً."""
        request = self._request_at_project_review('1234567802')
        with self.assertRaises(UserError):
            request.with_user(self.gm_user).action_direct_approve(reason='محاولة')

    def test_context_alone_grants_nothing(self):
        """السياق يمكن تمريره من أي عميل RPC - فلا يتخطى الفحص دون المجموعة."""
        request = self._request_at_project_review('1234567803')
        with self.assertRaises(UserError):
            request.with_user(self.gm_user).with_context(
                recruitment_direct_approval=True).action_approve()
        self.assertEqual(request.stage_id, self.stage_project_review)

    def test_group_alone_does_not_bypass_the_normal_button(self):
        """صاحب التجاوز يعتمد بالأزرار العادية كأي مستخدم - لا يتخطى القيود
        إلا حين يطلبها صراحةً بسبب مسجَّل."""
        request = self._request_at_project_review('1234567804')
        with self.assertRaises(UserError):
            request.with_user(self.override_user).action_approve()
        self.assertEqual(request.stage_id, self.stage_project_review)

    def test_data_requirements_are_still_enforced(self):
        """يتخطى مَن يعتمد لا ما يُشترط: طلب جديد بلا مرفقاته الإجبارية لا
        يُعتمد مباشرةً، ولا يتحرك من مكانه."""
        request = self.Request.create({
            'employee_name': 'مرشّح بلا مرفقات',
            'identification_id': '1234567805',
            'mobile': '0501234567',
            'email': 'no_attachments@example.com',
            'project_id': self.project.id,
        })
        if request.attachments_complete:
            self.skipTest('لا مرفقات إجبارية معرَّفة في هذه القاعدة')
        stage_before = request.stage_id
        with self.assertRaises(UserError):
            request.with_user(self.override_user).action_direct_approve(reason='عاجل')
        self.assertEqual(request.stage_id, stage_before)
        self.assertFalse(request.direct_approval_user_id)

    def test_reason_is_mandatory(self):
        request = self._request_at_project_review('1234567806')
        with self.assertRaises(UserError):
            request.with_user(self.override_user).action_direct_approve(reason='   ')

    def test_not_available_past_the_approval_stages(self):
        request = self._request_at_project_review('1234567807')
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_paid.id,
        })
        with self.assertRaises(UserError):
            request.with_user(self.override_user).action_direct_approve(reason='عاجل')
