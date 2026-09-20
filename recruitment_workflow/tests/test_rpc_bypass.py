# -*- coding: utf-8 -*-
"""ثغرات تجاوز مُثبتة بفحص مباشر - مغلقة الآن.

السياق في أودو يصل من العميل مع كل نداء RPC، فمفتاح مثل
``skip_stage_validation`` كان يرفع الحارس لأي مستخدم يمرّره.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentRpcBypass(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'مستخدم سير عمل عادي', 'login': 'rw_bypass_probe_user',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('recruitment_workflow.group_recruitment_workflow_user').id,
            ])],
        })
        cls.project = cls.env['project.project'].create({'name': 'مشروع فحص التجاوز'})

    def _request(self, identification_id, email):
        return self.env['recruitment.request'].with_user(self.user).create({
            'employee_name': 'مرشح فحص التجاوز',
            'identification_id': identification_id,
            'mobile': '0500000000',
            'email': email,
            'project_id': self.project.id,
        })

    def test_user_cannot_jump_stages_with_a_context_flag(self):
        """كان يمر: قفز الطلب إلى مرحلة اعتماد المدير العام بنداء RPC
        واحد يحمل skip_stage_validation."""
        request = self._request('2511223344', 'bypass1@example.com')
        gm_stage = self.env['recruitment.stage'].search(
            [('code', '=', 'gm_approval')], limit=1)
        self.assertTrue(gm_stage)

        with self.assertRaises(UserError):
            request.with_context(skip_stage_validation=True).write(
                {'stage_id': gm_stage.id})
        self.assertNotEqual(request.stage_id, gm_stage)

    def test_user_cannot_force_a_vehicle_change_request_to_done(self):
        employee = self.env['hr.employee'].create({'name': 'مندوب فحص التجاوز'})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة فحص'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل فحص', 'brand_id': brand.id})
        vehicle = self.env['fleet.vehicle'].create({'model_id': model.id})
        request = self.env['fleet.vehicle.change.request'].sudo().create({
            'employee_id': employee.id, 'request_type': 'plate',
            'current_vehicle_id': vehicle.id,
        })

        with self.assertRaises(UserError):
            request.with_user(self.user).with_context(
                vehicle_change_skip_state_guard=True).write({'state': 'done'})
        self.assertEqual(request.state, 'draft')
