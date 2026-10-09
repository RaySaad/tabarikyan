# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    rental_chargeable = fields.Boolean(
        string='خاضعة لتحميل الأجرة', default=True,
        help='ألغِ التحديد لمركبة لا تُحمَّل أجرتها على الفروع '
             '(مركبة إدارة، أو تحت التجربة).',
    )
    rental_monthly_rate = fields.Monetary(
        string='الأجرة الشهرية', currency_field='currency_id',
        help='تُحتسب يومياً بالتناسب على أيام تبعية المركبة للفرع. '
             'تغطي الاستهلاك والتأمين والاستمارة والصيانة الدورية '
             'والأعطال - أما الحوادث والتلفيات فعلى الفرع بنسبة تحمّله.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    rental_contract_ids = fields.One2many(
        'fleet.rental.contract', 'vehicle_id', string='عقود التأجير',
    )
    rental_contract_id = fields.Many2one(
        'fleet.rental.contract', string='العقد الساري',
        compute='_compute_rental_status', store=True,
    )
    rental_branch_id = fields.Many2one(
        'res.company', string='الفرع المستأجر',
        compute='_compute_rental_status', store=True,
    )
    # كل يوم ركود تكلفة صافية على الأسطول بلا مقابل - ولم يكن هناك ما
    # يُظهرها. مخزَّنة ليمكن الفرز والتصفية عليها.
    is_rental_idle = fields.Boolean(
        string='راكدة (بلا عقد)', compute='_compute_rental_status', store=True,
    )
    rental_idle_since = fields.Date(
        string='راكدة منذ', compute='_compute_rental_status', store=True,
    )
    rental_idle_days = fields.Integer(
        string='أيام الركود', compute='_compute_rental_idle_days',
    )

    @api.depends('rental_contract_ids.state', 'rental_contract_ids.date_end',
                 'rental_contract_ids.company_id')
    def _compute_rental_status(self):
        for vehicle in self:
            active = vehicle.rental_contract_ids.filtered(
                lambda c: c.state == 'active')[:1]
            vehicle.rental_contract_id = active
            vehicle.rental_branch_id = active.company_id
            vehicle.is_rental_idle = not active and vehicle.rental_chargeable
            if active:
                vehicle.rental_idle_since = False
            else:
                ended = vehicle.rental_contract_ids.filtered('date_end')
                vehicle.rental_idle_since = max(
                    ended.mapped('date_end')) if ended else False

    def _compute_rental_idle_days(self):
        today = fields.Date.context_today(self)
        for vehicle in self:
            if vehicle.is_rental_idle and vehicle.rental_idle_since:
                vehicle.rental_idle_days = (today - vehicle.rental_idle_since).days
            else:
                vehicle.rental_idle_days = 0

    def action_open_idle_cost(self):
        """تكلفة الركود التقديرية: الأجرة الضائعة منذ آخر إرجاع."""
        self.ensure_one()
        lost = self.rental_monthly_rate / 30.0 * self.rental_idle_days
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('تكلفة الركود التقديرية'),
                'message': _('%(days)s يوماً بلا عقد - أجرة ضائعة نحو %(amount)s.')
                % {'days': self.rental_idle_days, 'amount': round(lost, 2)},
                'type': 'warning',
                'sticky': False,
            },
        }
