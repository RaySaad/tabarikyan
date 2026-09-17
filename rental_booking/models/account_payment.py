# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # الرابط بين الدفعة وحجزها: يُسجَّل لحظة القبض من شاشة الحجز، فتُطابَق
    # الدفعة مع فاتورة *ذلك* الحجز تحديداً - لا تُختار من قائمة أرصدة
    # مفتوحة مشتركة بين كل النزلاء (العميل المحاسبي واحد).
    booking_order_id = fields.Many2one(
        'sale.order', string='حجز التأجير', index='btree_not_null',
        copy=False, ondelete='set null',
    )
