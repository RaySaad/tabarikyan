# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    is_fleet_owner = fields.Boolean(
        related='company_id.is_fleet_owner', readonly=False,
        string='هذه الشركة هي شركة الأسطول',
    )
    fleet_rental_start_date = fields.Date(
        related='company_id.fleet_rental_start_date', readonly=False,
        string='بداية احتساب الأجرة',
    )
    fleet_rental_journal_id = fields.Many2one(
        related='company_id.fleet_rental_journal_id', readonly=False,
        string='دفتر قيود التحميل',
    )
    fleet_rental_expense_account_id = fields.Many2one(
        related='company_id.fleet_rental_expense_account_id', readonly=False,
        string='حساب مصروف أجرة السيارات',
    )
    fleet_rental_interco_account_id = fields.Many2one(
        related='company_id.fleet_rental_interco_account_id', readonly=False,
        string='الحساب الجاري بين الفروع',
    )
    fleet_rental_income_account_id = fields.Many2one(
        related='company_id.fleet_rental_income_account_id', readonly=False,
        string='حساب استرداد تكلفة الأسطول',
    )
