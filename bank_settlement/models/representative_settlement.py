# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementRepresentative(models.Model):
    """تصفيات المناديب — كود Del/sett/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.representative'
    _description = 'تصفية مندوب'
    _inherit = ['bank.settlement.mixin']

    date = fields.Date(string='التاريخ', default=fields.Date.context_today)
    iban = fields.Char(string='الأيبان')

    # "ID رقم" في الفيديو — تعريف المندوب داخل تطبيق التوصيل (كيتا/جاهز/هنقرستيشن)
    platform_employee_id = fields.Char(string='ID رقم (داخل التطبيق)')

    settlement_amount = fields.Monetary(
        string='مبلغ التصفية', related='amount', readonly=False,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'مسددة'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.representative'
