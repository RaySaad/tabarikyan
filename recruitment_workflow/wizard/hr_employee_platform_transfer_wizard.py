# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformTransferWizard(models.TransientModel):
    _name = 'hr.employee.platform.transfer.wizard'
    _description = 'معالج نقل المندوب بين المنصات'

    employee_id = fields.Many2one(
        'hr.employee',
        string='المندوب',
        required=True,
    )
    current_project_id = fields.Many2one(
        'project.project',
        string='المنصة الحالية',
        readonly=True,
    )
    new_project_id = fields.Many2one(
        'project.project',
        string='المنصة الجديدة',
        required=True,
    )
    note = fields.Char(string='سبب/ملاحظة النقل')
    transfer_date = fields.Date(
        string='تاريخ النقل',
        default=fields.Date.context_today,
        required=True,
    )

    @api.constrains('new_project_id', 'current_project_id')
    def _check_different_project(self):
        for rec in self:
            if rec.new_project_id and rec.current_project_id \
                    and rec.new_project_id.id == rec.current_project_id.id:
                raise UserError(_(
                    'المندوب يعمل بالفعل على هذه المنصة. اختر منصة مختلفة لإتمام النقل.'
                ))

    def action_confirm_transfer(self):
        self.ensure_one()
        self.employee_id._open_platform_history(
            self.new_project_id, note=self.note, date_start=self.transfer_date,
        )
        # السيارة تبقى مع المندوب (لا تتبع المنصة) حسب سياسة الشركة، لذا لا
        # يوجد أي تعديل هنا على fleet.vehicle عمداً.
        return {'type': 'ir.actions.act_window_close'}
