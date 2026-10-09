# -*- coding: utf-8 -*-
from odoo import fields, models


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
