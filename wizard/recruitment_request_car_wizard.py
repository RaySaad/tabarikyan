# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentRequestCarWizard(models.TransientModel):
    _name = 'recruitment.request.car.wizard'
    _description = 'مساعد طلب سيارة من الأسطول'

    request_id = fields.Many2one(
        'recruitment.request',
        string='الطلب',
        required=True,
    )
    project_id = fields.Many2one(
        related='request_id.project_id',
        string='المشروع / المنصة',
        readonly=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='السيارة المتاحة',
        required=True,
        domain="[('recruitment_state', '=', 'available'), "
               "'|', ('project_id', '=', project_id), ('project_id', '=', False)]",
    )
    available_count = fields.Integer(
        string='عدد السيارات المتاحة (لنفس المنصة أو بدون منصة)',
        compute='_compute_available_count',
    )

    @api.depends('project_id')
    def _compute_available_count(self):
        for rec in self:
            domain = [('recruitment_state', '=', 'available')]
            if rec.project_id:
                domain += ['|', ('project_id', '=', rec.project_id.id), ('project_id', '=', False)]
            rec.available_count = self.env['fleet.vehicle'].search_count(domain)

    def action_send_request(self):
        self.ensure_one()
        if not self.vehicle_id:
            raise UserError(_('يجب اختيار سيارة متاحة.'))
        self.request_id.action_send_car_request(self.vehicle_id)
        return {'type': 'ir.actions.act_window_close'}
