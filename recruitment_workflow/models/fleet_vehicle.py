# -*- coding: utf-8 -*-
from odoo import models, fields, api


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    recruitment_state = fields.Selection(
        selection=[
            ('available', 'متاحة'),
            ('reserved', 'محجوزة (طلب توظيف)'),
            ('assigned', 'مخصصة'),
            ('unavailable', 'غير متاحة'),
        ],
        string='حالة التوفر للتوظيف',
        default='available',
        tracking=True,
        help='تحدد ما إذا كانت السيارة متاحة لتخصيصها في طلبات التوظيف.',
    )
    recruitment_request_ids = fields.One2many(
        'recruitment.request',
        'vehicle_id',
        string='طلبات التوظيف المرتبطة',
    )
    recruitment_request_count = fields.Integer(
        string='عدد الطلبات',
        compute='_compute_recruitment_request_count',
    )

    @api.depends('recruitment_request_ids')
    def _compute_recruitment_request_count(self):
        for rec in self:
            rec.recruitment_request_count = len(rec.recruitment_request_ids)

    def action_set_available(self):
        self.write({'recruitment_state': 'available'})

    def action_set_unavailable(self):
        self.write({'recruitment_state': 'unavailable'})
