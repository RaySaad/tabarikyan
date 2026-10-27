# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    settlement_dues_account_code = fields.Char(
        related='company_id.settlement_dues_account_code', readonly=False,
    )
