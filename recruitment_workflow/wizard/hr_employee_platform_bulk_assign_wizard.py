# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformBulkAssignWizard(models.TransientModel):
    _name = 'hr.employee.platform.bulk.assign.wizard'
    _description = 'ربط عدة موظفين قدامى بمنصة دفعة واحدة'

    line_ids = fields.One2many(
        'hr.employee.platform.bulk.assign.wizard.line',
        'wizard_id',
        string='الموظفون',
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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            employee_ids = self.env.context.get('active_ids')
            if employee_ids:
                employees = self.env['hr.employee'].browse(employee_ids)
                res['line_ids'] = [
                    (0, 0, {
                        'employee_id': employee.id,
                        # تاريخ إنشاء سجل الموظف يعكس تاريخ تعيينه الفعلي
                        # لهؤلاء الموظفين القدامى - يبقى قابلاً للتعديل يدوياً.
                        'date_start': employee.create_date.date()
                        if employee.create_date else fields.Date.context_today(self),
                    })
                    for employee in employees
                ]
        return res

    @api.depends('line_ids')
    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.line_ids)

    def action_confirm_assign(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('لم يتم تحديد أي موظف.'))
        for line in self.line_ids:
            line.employee_id._open_platform_history(
                self.project_id, note=self.note, date_start=line.date_start,
            )
        return {'type': 'ir.actions.act_window_close'}


class HrEmployeePlatformBulkAssignWizardLine(models.TransientModel):
    _name = 'hr.employee.platform.bulk.assign.wizard.line'
    _description = 'سطر ربط موظف بمنصة (معالج الربط الجماعي)'

    wizard_id = fields.Many2one(
        'hr.employee.platform.bulk.assign.wizard',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='الموظف',
        required=True,
    )
    date_start = fields.Date(
        string='تاريخ بداية العمل على المنصة',
        required=True,
        default=fields.Date.context_today,
        help='مقترح تلقائياً من تاريخ تعيين الموظف (تاريخ إنشاء سجله)، '
             'ويمكن تعديله لكل موظف على حدة قبل التأكيد.',
    )
