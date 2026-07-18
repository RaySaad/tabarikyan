# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrEmployeePlatformBulkAssign(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env['hr.employee']
        cls.Wizard = cls.env['hr.employee.platform.bulk.assign.wizard']
        cls.project = cls.env['project.project'].create({'name': 'منصة تجريبية للربط الجماعي'})

    def test_bulk_assign_links_employees_without_prior_platform(self):
        """الربط الجماعي يعمل للموظفين القدامى الذين لا منصة لهم أصلاً -
        يُنشئ سجل تاريخ منصات لكل واحد منهم ويحدّث المنصة الحالية."""
        employees = self.Employee.create([
            {'name': 'موظف قديم 1'},
            {'name': 'موظف قديم 2'},
        ])
        self.assertFalse(employees.mapped('project_id').filtered(lambda p: p))

        wizard = self.Wizard.create({
            'employee_ids': [(6, 0, employees.ids)],
            'project_id': self.project.id,
            'note': 'ربط رجعي - اختبار',
        })
        wizard.action_confirm_assign()

        for employee in employees:
            self.assertEqual(employee.project_id, self.project)
            self.assertEqual(len(employee.platform_history_ids), 1)
            self.assertTrue(employee.platform_history_ids.is_current)

    def test_bulk_assign_does_not_duplicate_open_period_for_same_project(self):
        """موظف مرتبط أصلاً بنفس المنصة لا يُنشأ له سجل تاريخ مكرر."""
        employee = self.Employee.create({'name': 'موظف مرتبط مسبقاً'})
        employee._open_platform_history(self.project)
        self.assertEqual(len(employee.platform_history_ids), 1)

        wizard = self.Wizard.create({
            'employee_ids': [(6, 0, employee.ids)],
            'project_id': self.project.id,
        })
        wizard.action_confirm_assign()

        self.assertEqual(len(employee.platform_history_ids), 1)

    def test_bulk_assign_uses_custom_start_date(self):
        """تاريخ البداية يجب أن يعكس التاريخ الذي يحدّده المستخدم (ربط
        رجعي) وليس دائماً تاريخ اليوم."""
        employee = self.Employee.create({'name': 'موظف قديم بتاريخ رجعي'})
        past_date = date.today() - timedelta(days=365)

        wizard = self.Wizard.create({
            'employee_ids': [(6, 0, employee.ids)],
            'project_id': self.project.id,
            'date_start': past_date,
        })
        wizard.action_confirm_assign()

        self.assertEqual(employee.platform_history_ids.date_start, past_date)

    def test_transfer_wizard_uses_selected_transfer_date(self):
        """معالج النقل الفردي يجب أن يستخدم فعلياً تاريخ النقل الذي يحدّده
        المستخدم، لا تاريخ اليوم دائماً."""
        employee = self.Employee.create({'name': 'موظف للنقل'})
        past_date = date.today() - timedelta(days=30)

        transfer_wizard = self.env['hr.employee.platform.transfer.wizard'].create({
            'employee_id': employee.id,
            'new_project_id': self.project.id,
            'transfer_date': past_date,
        })
        transfer_wizard.action_confirm_transfer()

        self.assertEqual(employee.platform_history_ids.date_start, past_date)
