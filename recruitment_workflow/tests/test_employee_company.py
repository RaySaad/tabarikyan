# -*- coding: utf-8 -*-
"""شركة السجل تتبع الموظف لا مبدِّل الشركات.

كانت كل هذه السجلات تأخذ شركة المستخدم لحظة الإنشاء، وعليها قاعدة
عزل بالشركة - فطلبُ موظفٍ في فرع يُسجَّل على فرع منشئه ويختفي عن
فرع صاحبه.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.main = cls.env.company
        cls.branch = cls.env['res.company'].create({'name': 'فرع شركة الموظف'})
        cls.env.user.company_ids |= cls.branch
        cls.employee = cls.env['hr.employee'].create({
            'name': 'موظف الفرع', 'company_id': cls.branch.id})
        cls.project = cls.env['project.project'].create({'name': 'منصة اختبار الشركة'})
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'ماركة اختبار الشركة'})
        model = cls.env['fleet.vehicle.model'].create({
            'name': 'موديل اختبار الشركة', 'brand_id': brand.id})
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'company_id': cls.branch.id})

    # ---- السجلات الستة ----
    def test_platform_transfer_follows_the_employee(self):
        request = self.env['hr.employee.platform.transfer.request'].create({
            'employee_id': self.employee.id, 'new_project_id': self.project.id})
        self.assertEqual(request.company_id, self.branch)

    def test_exit_request_follows_the_employee(self):
        request = self.env['hr.employee.exit.request'].create({
            'employee_id': self.employee.id, 'last_working_date': '2026-11-01'})
        self.assertEqual(request.company_id, self.branch)

    def test_warning_follows_the_employee(self):
        warning_type = self.env['hr.employee.warning.type'].search([], limit=1) \
            or self.env['hr.employee.warning.type'].create({'name': 'نوع اختبار'})
        warning = self.env['hr.employee.warning'].create({
            'employee_id': self.employee.id, 'warning_type_id': warning_type.id})
        self.assertEqual(warning.company_id, self.branch)

    def test_platform_history_follows_the_employee(self):
        line = self.env['hr.employee.platform.history'].create({
            'employee_id': self.employee.id, 'project_id': self.project.id,
            'date_start': '2026-01-01'})
        self.assertEqual(line.company_id, self.branch)

    def test_vehicle_change_request_follows_the_employee(self):
        request = self.env['fleet.vehicle.change.request'].create({
            'employee_id': self.employee.id, 'request_type': 'plate',
            'current_vehicle_id': self.vehicle.id})
        self.assertEqual(request.company_id, self.branch)

    def test_accident_report_follows_the_employee(self):
        report = self.env['fleet.accident.report'].create({
            'employee_id': self.employee.id, 'vehicle_id': self.vehicle.id})
        self.assertEqual(report.company_id, self.branch)

    # ---- المصدر البديل ----
    def test_accident_report_without_a_driver_follows_the_vehicle(self):
        """بلاغ بلا سائق محدَّد: المركبة هي صاحبة الفرع."""
        report = self.env['fleet.accident.report'].create({
            'vehicle_id': self.vehicle.id})
        self.assertEqual(report.company_id, self.branch)

    # ---- التغيير اللاحق ----
    def test_changing_the_employee_moves_the_company_with_him(self):
        other_branch = self.env['res.company'].create({'name': 'فرع آخر'})
        self.env.user.company_ids |= other_branch
        other_employee = self.env['hr.employee'].create({
            'name': 'موظف الفرع الآخر', 'company_id': other_branch.id})
        request = self.env['hr.employee.platform.transfer.request'].create({
            'employee_id': self.employee.id, 'new_project_id': self.project.id})

        request.write({'employee_id': other_employee.id})

        self.assertEqual(request.company_id, other_branch)

    def test_employee_without_a_company_keeps_the_user_company(self):
        """لا نترك الحقل فارغاً: موظف بلا فرع يبقى السجل على فرع منشئه."""
        free_employee = self.env['hr.employee'].sudo().create(
            {'name': 'موظف بلا فرع'})
        free_employee.sudo().write({'company_id': False})
        request = self.env['hr.employee.platform.transfer.request'].create({
            'employee_id': free_employee.id, 'new_project_id': self.project.id})
        self.assertEqual(request.company_id, self.main)
