# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class RecruitmentRequestCarWizard(models.TransientModel):
    _name = 'recruitment.request.car.wizard'
    _description = 'مساعد طلب سيارة من الأسطول'

    request_id = fields.Many2one(
        'recruitment.request',
        string='الطلب',
        required=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='السيارة المتاحة',
        required=True,
        domain="[('recruitment_state', '=', 'available')]",
    )
    available_count = fields.Integer(
        string='عدد السيارات المتاحة',
        compute='_compute_available_count',
    )

    def _compute_available_count(self):
        count = self.env['fleet.vehicle'].search_count(
            [('recruitment_state', '=', 'available')]
        )
        for rec in self:
            rec.available_count = count

    def action_send_request(self):
        self.ensure_one()
        if not self.vehicle_id:
            raise UserError(_('يجب اختيار سيارة متاحة.'))
        self.request_id.action_send_car_request(self.vehicle_id)
        return {'type': 'ir.actions.act_window_close'}
