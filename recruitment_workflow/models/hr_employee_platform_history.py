# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrEmployeePlatformHistory(models.Model):
    _name = 'hr.employee.platform.history'
    _description = 'سجل تاريخ منصات المندوب'
    _inherit = ['recruitment.workflow.analytic.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'project_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='المندوب',
        required=True,
        ondelete='cascade',
        index=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='المشروع / المنصة',
        required=True,
        index=True,
    )
    date_start = fields.Date(string='تاريخ البداية', required=True)
    date_end = fields.Date(
        string='تاريخ النهاية',
        help='يبقى فارغاً طالما المندوب لا يزال يعمل على هذه المنصة حالياً.',
    )
    is_current = fields.Boolean(
        string='الفترة الحالية',
        compute='_compute_is_current',
        store=True,
    )
    note = fields.Char(string='ملاحظة النقل')
    company_id = fields.Many2one(
        'res.company',
        string='الشركة',
        default=lambda self: self.env.company,
    )

    @api.depends('date_end')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.date_end
