# -*- coding: utf-8 -*-
from odoo import _, fields, models


class RecruitmentRequest(models.Model):
    _inherit = 'recruitment.request'

    rental_contract_id = fields.Many2one(
        'fleet.rental.contract', string='عقد التأجير', readonly=True, copy=False,
        help='يصدر بموافقة الأسطول على طلب السيارة - خطوة واحدة لا دورتا '
             'اعتماد.',
    )

    def action_fleet_authorize(self):
        """موافقة الأسطول تُخصّص المركبة وتُصدر العقد في آنٍ واحد."""
        res = super().action_fleet_authorize()
        Contract = self.env['fleet.rental.contract']
        for rec in self:
            if not rec.vehicle_id or rec.rental_contract_id:
                continue
            contract = Contract._issue_for_assignment(
                rec.vehicle_id, rec.company_id,
                employee=rec.employee_id, request=rec,
                date_start=fields.Date.context_today(rec),
            )
            if contract:
                rec.rental_contract_id = contract.id
                rec.message_post(body=_(
                    'صدر عقد التأجير %(contract)s: المركبة %(vehicle)s '
                    'للفرع %(branch)s بأجرة %(rate)s شهرياً.'
                ) % {'contract': contract.name,
                     'vehicle': rec.vehicle_id.display_name,
                     'branch': rec.company_id.display_name,
                     'rate': contract.monthly_rate})
        return res

    def action_view_rental_contract(self):
        self.ensure_one()
        return {
            'name': _('عقد التأجير'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.rental.contract',
            'res_id': self.rental_contract_id.id,
            'view_mode': 'form',
        }
