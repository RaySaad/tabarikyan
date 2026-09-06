# -*- coding: utf-8 -*-
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeDiscipline(TransactionCase):
    """اختبارات الإنذارات وإنهاء الخدمة: التصعيد التلقائي، تجميد المستوى،
    سقوط الإنذار بالتقادم، الإنشاء التلقائي لطلب إنهاء الخدمة عند الإنذار
    النهائي، وكل آثار تنفيذ الخروج (سحب المركبة، إغلاق المنصة، الأرشفة)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Warning = cls.env['hr.employee.warning']
        cls.Exit = cls.env['hr.employee.exit.request']
        cls.warning_type = cls.env.ref('recruitment_workflow.warning_type_absence')

        cls.partner = cls.env['res.partner'].create({'name': 'مندوب الانضباط'})
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'مندوب الانضباط', 'work_contact_id': cls.partner.id,
        })

        plan = cls.env['account.analytic.plan'].sudo().search([], limit=1) \
            or cls.env['account.analytic.plan'].sudo().create({'name': 'خطة'})
        analytic = cls.env['account.analytic.account'].sudo().create({
            'name': 'تحليلي الانضباط', 'plan_id': plan.id,
        })
        cls.platform = cls.env['project.project'].sudo().create({
            'name': 'منصة الانضباط', 'account_id': analytic.id,
        })
        cls.employee._open_platform_history(cls.platform, date_start=date(2024, 1, 1))

        brand = cls.env['fleet.vehicle.model.brand'].sudo().create({'name': 'ماركة الانضباط'})
        model = cls.env['fleet.vehicle.model'].sudo().create({
            'name': 'موديل الانضباط', 'brand_id': brand.id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].sudo().create({
            'model_id': model.id, 'license_plate': 'EXIT-001',
            'company_id': cls.env.company.id,
            'driver_id': cls.partner.id, 'recruitment_state': 'assigned',
        })

        cls.approver = cls.env['res.users'].sudo().create({
            'name': 'معتمِد الانضباط', 'login': 'test_discipline_approver',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('recruitment_workflow.group_recruitment_workflow_manager').id,
            ])],
        })
        cls.plain_user = cls.env['res.users'].sudo().create({
            'name': 'مستخدم الانضباط', 'login': 'test_discipline_plain',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('recruitment_workflow.group_recruitment_workflow_user').id,
            ])],
        })

    def _warn(self, on_date=None, confirm=True):
        warning = self.Warning.create({
            'employee_id': self.employee.id,
            'warning_type_id': self.warning_type.id,
            'date': on_date or date.today(),
        })
        if confirm:
            warning.with_user(self.approver).action_confirm()
        return warning

    # ------------------------------------------------------------------
    def test_levels_escalate_automatically(self):
        first, second, third = self._warn(), self._warn(), self._warn()
        self.assertEqual(first.level_number, 1)
        self.assertEqual(second.level_number, 2)
        self.assertEqual(third.level_number, 3)
        self.assertFalse(first.is_final)
        self.assertFalse(second.is_final)
        self.assertTrue(third.is_final)

    def test_level_is_frozen_after_confirmation(self):
        """مستوى الإنذار لا يُعاد حسابه أبداً بعد الاعتماد - وإلا تغيّر
        سجل تأديبي موقَّع من الموظف كلما سقط إنذار آخر بالتقادم."""
        first = self._warn()
        second = self._warn()
        self.assertEqual(second.level_number, 2)
        first.with_user(self.approver).action_cancel()
        self.assertEqual(second.level_number, 2)

    def test_expired_warning_does_not_escalate(self):
        """إنذار مضى عليه أكثر من مدة السريان لا يُحتسب في التصعيد."""
        old = self._warn(on_date=date.today() - relativedelta(months=18))
        self.assertTrue(old.expiry_date < date.today())
        self.assertTrue(old.is_expired)
        fresh = self._warn()
        self.assertEqual(fresh.level_number, 1)

    def test_expiry_follows_configured_policy(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'recruitment_workflow.warning_validity_months', '6')
        warning = self._warn()
        self.assertEqual(
            warning.expiry_date, warning.date + relativedelta(months=6))
        self.env['ir.config_parameter'].sudo().set_param(
            'recruitment_workflow.warning_validity_months', '12')

    def test_configured_count_changes_final_level(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'recruitment_workflow.warning_count', '2')
        self._warn()
        second = self._warn()
        self.assertTrue(second.is_final)
        self.env['ir.config_parameter'].sudo().set_param(
            'recruitment_workflow.warning_count', '3')

    def test_final_warning_creates_draft_exit_request(self):
        self._warn()
        self._warn()
        final = self._warn()
        self.assertTrue(final.exit_request_id)
        request = final.exit_request_id
        self.assertEqual(request.state, 'draft')
        self.assertEqual(request.exit_type, 'termination')
        self.assertEqual(request.employee_id, self.employee)
        # الفصل لا يقع تلقائياً
        self.assertTrue(self.employee.active)

    def test_warning_requires_group_and_cannot_be_deleted_after_confirm(self):
        warning = self._warn(confirm=False)
        with self.assertRaises(UserError):
            warning.with_user(self.plain_user).action_confirm()
        warning.with_user(self.approver).action_confirm()
        with self.assertRaises(UserError):
            warning.unlink()

    # -- إنهاء الخدمة ------------------------------------------------------
    def _exit_request(self, **kwargs):
        vals = {
            'employee_id': self.employee.id,
            'exit_type': 'resignation',
            'last_working_date': date.today(),
        }
        vals.update(kwargs)
        return self.Exit.create(vals)

    def test_exit_execution_side_effects(self):
        request = self._exit_request()
        # المعلقات تُعرَض (المركبة على الأقل) بلا منع
        self.assertIn('EXIT-001', request.pending_items or '')

        request.action_submit_review()
        request.with_user(self.approver).action_pm_approve()
        request.with_user(self.approver).action_confirm_exit()

        self.assertEqual(request.state, 'done')
        # 1) طلب سحب المركبة أُنشئ (ولم تُحرَّر المركبة مباشرة)
        vehicle_request = request.vehicle_change_request_id
        self.assertTrue(vehicle_request)
        self.assertEqual(vehicle_request.request_type, 'exit')
        self.assertFalse(vehicle_request.new_vehicle_id)
        self.assertEqual(vehicle_request.old_vehicle_target_state, 'available')
        self.assertEqual(self.vehicle.recruitment_state, 'assigned')
        # 2) فترة المنصة أُغلقت
        history = self.employee.sudo().platform_history_ids
        self.assertTrue(all(h.date_end for h in history))
        self.assertFalse(self.employee.sudo().project_id)
        # 3) بيانات المغادرة والأرشفة
        employee = self.employee.sudo()
        self.assertFalse(employee.active)
        self.assertEqual(employee.departure_date, date.today())
        self.assertTrue(employee.departure_reason_id)

    def test_vehicle_becomes_available_only_after_receipt(self):
        """المركبة لا تعود "متاحة" إلا بعد استلامها فعلياً من قسم الحركة."""
        request = self._exit_request()
        request.action_submit_review()
        request.with_user(self.approver).action_pm_approve()
        request.with_user(self.approver).action_confirm_exit()
        vehicle_request = request.vehicle_change_request_id

        vehicle_request.action_submit_review()
        vehicle_request.with_user(self.approver).action_supervisor_approve()
        # نوع "خروج مندوب" يتخطى مرحلة الصيانة
        self.assertEqual(vehicle_request.state, 'waiting_ops')
        vehicle_request.with_user(self.approver).action_ops_approve()
        vehicle_request.with_user(self.approver).action_manager_confirm()
        self.assertEqual(self.vehicle.recruitment_state, 'assigned')

        vehicle_request.write({'receipt_odometer': 4321.0})
        vehicle_request.with_user(self.approver).action_confirm_receipt()
        self.assertEqual(self.vehicle.recruitment_state, 'available')
        self.assertFalse(self.vehicle.driver_id)

    def test_single_open_exit_request_per_employee(self):
        self._exit_request()
        with self.assertRaises(UserError):
            self._exit_request()

    def test_exit_locked_fields_and_delete_protection(self):
        request = self._exit_request()
        request.action_submit_review()
        with self.assertRaises(UserError):
            request.write({'last_working_date': date.today() - timedelta(days=5)})
        with self.assertRaises(UserError):
            request.unlink()

    def test_done_exit_cannot_be_cancelled(self):
        request = self._exit_request()
        request.action_submit_review()
        request.with_user(self.approver).action_pm_approve()
        request.with_user(self.approver).action_confirm_exit()
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_cancel()

    def test_employee_with_discipline_records_cannot_be_deleted(self):
        self._warn()
        with self.assertRaises(UserError):
            self.employee.sudo().unlink()
