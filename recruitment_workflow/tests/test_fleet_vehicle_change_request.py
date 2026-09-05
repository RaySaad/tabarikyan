# -*- coding: utf-8 -*-
import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFleetVehicleChangeRequest(TransactionCase):
    """اختبارات طلب تغيير المركبة - تغطي المسار الكامل لكل نوع طلب،
    تخطي مرحلة الصيانة في طلبات "لوحة"، الإنشاء التلقائي لبلاغ الحادث
    وسجل الصيانة، سحب المركبة بلا بديل، وكل الحمايات (المرفقات
    الإجبارية، قفل الحقول، منع القفز بين المراحل، حراس التنفيذ)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['fleet.vehicle.change.request']
        cls.Vehicle = cls.env['fleet.vehicle'].sudo()
        cls.file_content = base64.b64encode(b'test-attachment')

        cls.partner = cls.env['res.partner'].create({'name': 'مندوب اختبار المركبات'})
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'مندوب اختبار المركبات',
            'work_contact_id': cls.partner.id,
        })

        brand = cls.env['fleet.vehicle.model.brand'].sudo().create({'name': 'ماركة اختبار'})
        model = cls.env['fleet.vehicle.model'].sudo().create({
            'name': 'موديل اختبار', 'brand_id': brand.id,
        })
        vehicle_vals = {'model_id': model.id, 'company_id': cls.env.company.id}
        cls.vehicle_old = cls.Vehicle.create(dict(
            vehicle_vals, license_plate='OLD-001',
            driver_id=cls.partner.id, recruitment_state='assigned',
        ))
        cls.vehicle_new = cls.Vehicle.create(dict(
            vehicle_vals, license_plate='NEW-001', recruitment_state='available',
        ))

        # مستخدم يملك كل صلاحيات الحركة/الصيانة/العمليات (عبر مجموعة
        # "مدير سير العمل" التي تشملها جميعاً) - يمثّل كل المعتمِدين في
        # اختبار المسار، بينما plain_user يمثّل من لا يملك أي صلاحية.
        cls.approver = cls.env['res.users'].sudo().create({
            'name': 'معتمِد اختبار', 'login': 'test_vcr_approver',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('recruitment_workflow.group_recruitment_workflow_manager').id,
            ])],
        })
        cls.plain_user = cls.env['res.users'].sudo().create({
            'name': 'مستخدم اختبار عادي', 'login': 'test_vcr_plain',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('recruitment_workflow.group_recruitment_workflow_user').id,
            ])],
        })

    def _create_request(self, **kwargs):
        vals = {
            'employee_id': self.employee.id,
            'request_type': 'breakdown',
            'current_vehicle_id': self.vehicle_old.id,
            'new_vehicle_id': self.vehicle_new.id,
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    def _upload_required_attachments(self, request):
        for line in request.attachment_line_ids.filtered('required'):
            line.write({'file': self.file_content, 'file_name': 'test.pdf'})

    def _approve_until_manager(self, request):
        request.action_submit_review()
        request.with_user(self.approver).action_supervisor_approve()
        if request.state == 'waiting_maintenance':
            request.with_user(self.approver).action_maintenance_approve()
        request.with_user(self.approver).action_ops_approve()

    def _approve_and_receive(self, request, receipt_odometer=1000.0):
        """المسار الكامل حتى التنفيذ الفعلي - الذي صار يقع لحظة تأكيد
        الاستلام المادي وليس عند اعتماد مدير الحركة."""
        self._approve_until_manager(request)
        request.with_user(self.approver).action_manager_confirm()
        request.write({'receipt_odometer': receipt_odometer})
        request.with_user(self.approver).action_confirm_receipt()

    # ------------------------------------------------------------------
    def test_breakdown_full_flow_executes_change(self):
        request = self._create_request()
        self.assertTrue(request.attachment_line_ids)
        self._upload_required_attachments(request)
        self._approve_until_manager(request)
        self.assertEqual(request.state, 'waiting_manager')
        self.assertTrue(request.approval_date)

        # الاعتماد وحده لا ينفّذ شيئاً على المركبات
        request.with_user(self.approver).action_manager_confirm()
        self.assertEqual(request.state, 'waiting_receipt')
        self.assertEqual(self.vehicle_old.driver_id, self.partner)
        self.assertEqual(self.vehicle_old.recruitment_state, 'assigned')

        request.write({'receipt_odometer': 12345.0, 'delivery_odometer': 500.0})
        request.with_user(self.approver).action_confirm_receipt()

        self.assertEqual(request.state, 'done')
        self.assertTrue(request.receipt_date)
        self.assertEqual(request.receipt_user_id, self.approver)
        self.assertFalse(self.vehicle_old.driver_id)
        self.assertEqual(self.vehicle_old.recruitment_state, 'under_repair')
        self.assertEqual(self.vehicle_new.driver_id, self.partner)
        self.assertEqual(self.vehicle_new.recruitment_state, 'assigned')
        self.assertTrue(request.authorization_date)
        # "عطل" ينشئ سجل صيانة قياسياً على المركبة القديمة
        self.assertTrue(request.maintenance_log_id)
        self.assertEqual(request.maintenance_log_id.vehicle_id, self.vehicle_old)

    def test_plate_request_skips_maintenance_stage(self):
        request = self._create_request(request_type='plate')
        self.assertNotIn('waiting_maintenance', request._get_state_sequence())
        request.action_submit_review()
        request.with_user(self.approver).action_supervisor_approve()
        # ينتقل مباشرة لمدير العمليات بلا مرور بمرحلة الصيانة
        self.assertEqual(request.state, 'waiting_ops')

    def test_accident_request_creates_report_automatically(self):
        request = self._create_request(request_type='accident', new_vehicle_id=False)
        self.assertIn('waiting_maintenance', request._get_state_sequence())
        self._upload_required_attachments(request)
        self._approve_and_receive(request)

        self.assertEqual(request.state, 'done')
        self.assertTrue(request.accident_report_id)
        self.assertEqual(request.accident_report_id.vehicle_id, self.vehicle_old)
        self.assertEqual(request.accident_report_id.employee_id, self.employee)
        self.assertEqual(request.accident_report_id.state, 'draft')

    def test_withdraw_vehicle_without_replacement(self):
        """المركبة الجديدة اختيارية - سحب بلا بديل يترك المندوب بلا مركبة."""
        request = self._create_request(request_type='plate', new_vehicle_id=False)
        self._approve_and_receive(request)

        self.assertEqual(request.state, 'done')
        self.assertFalse(self.vehicle_old.driver_id)
        self.assertFalse(self.employee._get_current_vehicle())

    def test_required_attachments_block_submit(self):
        request = self._create_request()
        with self.assertRaises(UserError):
            request.action_submit_review()

    def test_approval_requires_group(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.with_user(self.plain_user).action_supervisor_approve()

    def test_locked_fields_after_submit(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.write({'current_vehicle_id': self.vehicle_new.id})

    def test_cannot_jump_stages(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.write({'state': 'waiting_manager'})

    def test_cannot_delete_after_submit(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.unlink()

    def test_same_vehicle_rejected(self):
        # assertRaises المُعاد تعريفه في أودو لا يقبل tuple من الاستثناءات
        # (يستدعي issubclass على الوسيط مباشرة) - لذا استثناء واحد فقط.
        with self.assertRaises(UserError):
            self._create_request(new_vehicle_id=self.vehicle_old.id)

    def test_execution_blocked_when_new_vehicle_no_longer_available(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        self._approve_until_manager(request)
        request.with_user(self.approver).action_manager_confirm()
        self.vehicle_new.write({'recruitment_state': 'unavailable'})
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_confirm_receipt()

    def test_execution_blocked_when_current_driver_changed(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        self._approve_until_manager(request)
        request.with_user(self.approver).action_manager_confirm()
        other_partner = self.env['res.partner'].create({'name': 'سائق آخر'})
        self.vehicle_old.write({'driver_id': other_partner.id})
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_confirm_receipt()

    def test_reset_to_draft_requires_reason(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.action_reset_draft()
        request.with_user(self.approver).action_reset_draft(reason='سبب اختبار')
        self.assertEqual(request.state, 'draft')
        self.assertTrue(request.rejection_reason)

    def test_done_request_cannot_be_reset_or_cancelled(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        self._approve_and_receive(request)
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_reset_draft(reason='محاولة')
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_cancel()

    def test_accident_report_close_requires_responsibility(self):
        report = self.env['fleet.accident.report'].create({
            'vehicle_id': self.vehicle_old.id,
            'employee_id': self.employee.id,
        })
        report.with_user(self.approver).action_confirm()
        with self.assertRaises(UserError):
            report.with_user(self.approver).action_close()
        report.write({'responsibility': 'employee'})
        report.with_user(self.approver).action_close()
        self.assertEqual(report.state, 'closed')

    def test_attachment_lines_follow_request_type(self):
        """تغيير نوع الطلب يعيد بناء المرفقات المطلوبة - مع الاحتفاظ بأي
        سطر رُفع فيه ملف فعلاً حتى لا يفقد المستخدم مستنداً رفعه."""
        request = self._create_request(request_type='breakdown')
        breakdown_types = request.attachment_line_ids.mapped('attachment_type_id')
        self.assertTrue(breakdown_types)
        request.write({'request_type': 'accident'})
        accident_types = request.attachment_line_ids.mapped('attachment_type_id')
        self.assertTrue(accident_types)
        self.assertFalse(accident_types & breakdown_types)

    def test_receipt_records_odometer_in_standard_log(self):
        """قراءة العداد عند الاستلام تُسجَّل في سجل العدادات القياسي بأودو،
        فيتحدّث كيلومتر المركبة في بطاقتها وتقاريرها المعتادة."""
        request = self._create_request()
        self._upload_required_attachments(request)
        self._approve_until_manager(request)
        request.with_user(self.approver).action_manager_confirm()
        request.write({'receipt_odometer': 55555.0})
        request.with_user(self.approver).action_confirm_receipt()

        logs = self.env['fleet.vehicle.odometer'].sudo().search([
            ('vehicle_id', '=', self.vehicle_old.id), ('value', '=', 55555.0),
        ])
        self.assertTrue(logs, 'لم تُسجَّل قراءة العداد في السجل القياسي')

    def test_receipt_requires_group(self):
        request = self._create_request()
        self._upload_required_attachments(request)
        self._approve_until_manager(request)
        request.with_user(self.approver).action_manager_confirm()
        with self.assertRaises(UserError):
            request.with_user(self.plain_user).action_confirm_receipt()
