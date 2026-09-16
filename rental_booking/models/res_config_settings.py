# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rental_cash_partner_id = fields.Many2one(
        related='company_id.rental_cash_partner_id', readonly=False,
        string='عميل الحجوزات النقدية',
    )
    rental_contract_terms = fields.Html(
        related='company_id.rental_contract_terms', readonly=False,
        string='بنود عقد الإيجار',
    )
    rental_platform_partner_id = fields.Many2one(
        related='company_id.rental_platform_partner_id', readonly=False,
        string='عميل منصة الحجز (جاذرن)',
    )
