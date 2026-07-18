# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformBulkAssignWizard(models.TransientModel):
    _name = 'hr.employee.platform.bulk.assign.wizard'
    _description = 'ربط عدة موظفين قدامى بمنصة دفعة واحدة'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='الموظفون',
        required=True,
    )
    employee_count = fields.Integer(
        string='عدد الموظفين',
        compute='_compute_employee_count',
    )
    project_id = fields.Many2one(
        'project.project',
        string='المنصة / المشروع',
        required=True,
        options="{'no_create': True}",
    )
    note = fields.Char(
        string='ملاحظة',
        help='تُسجَّل في سجل تاريخ المنصات لكل موظف (مثال: "ربط رجعي - بيانات قديمة").',
    )

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.employee_ids)

    def action_confirm_assign(self):
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_('لم يتم تحديد أي موظف.'))
        for employee in self.employee_ids:
            employee._open_platform_history(self.project_id, note=self.note)
        return {'type': 'ir.actions.act_window_close'}
