# -*- coding: utf-8 -*-
"""تخلّي المندوب عن الطلب - بالرفض الصريح أو بالصمت.

الإسناد كان جبراً بلا قبول: يُسنَد الطلب للمندوب ويظهر في تطبيقه،
فإن نام أو نسي جواله أو انقطع إنترنته أو رفضه بالصمت **بقي معلّقاً
عليه إلى الأبد** - المجدول يلتقط "جاري البحث" فقط. والمندوب يبقى
"مشغولاً" فلا تصله طلبات أخرى: طلبٌ ضائع ومندوبٌ معطَّل بسبب واحد.

هذا السجلّ هو ذاكرة ذلك: من تُرك عنده الطلب ولماذا. وهو مصدر
الاستبعاد عند إعادة الإسناد - بلا سجلٍّ يعود الإسناد إلى نفس المندوب
بعد ثوانٍ لأنه الأقرب، فيدور الطلب في محلّه حتى ينتهي وقته.
"""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class QuickDeliveryDecline(models.Model):
    _name = 'quick.delivery.decline'
    _description = 'تخلٍّ عن طلب'
    _order = 'id desc'

    order_id = fields.Many2one('quick.delivery.order', string='الطلب',
                               required=True, ondelete='cascade', index=True)
    driver_id = fields.Many2one('quick.delivery.driver', string='المندوب',
                                required=True, ondelete='cascade', index=True)
    client_id = fields.Many2one(related='order_id.client_id', store=True,
                                string='الشركة')
    kind = fields.Selection([
        ('declined', 'رفض صراحةً'),
        ('timeout', 'لم يستجب'),
        ('released', 'سُحب من غرفة العمليات'),
    ], string='النوع', required=True, default='declined', index=True)
    reason = fields.Char(string='السبب')
    seconds_waited = fields.Integer(string='ثوانٍ قبل السحب')

    # مرةٌ واحدة لكل مندوب في كل طلب: التدوير يستبعده بعدها، فلا معنى
    # لسجلٍّ ثانٍ، ولو أعادته غرفة العمليات يدوياً.
    _one_per_driver = models.Constraint(
        'unique(order_id, driver_id)',
        'سُجّل تخلّي هذا المندوب عن هذا الطلب بالفعل.')

    @api.model
    def _record(self, order, driver, kind, reason='', seconds=0):
        existing = self.sudo().search([('order_id', '=', order.id),
                                       ('driver_id', '=', driver.id)], limit=1)
        values = {'kind': kind, 'reason': (reason or '')[:200],
                  'seconds_waited': seconds}
        if existing:
            existing.write(values)
            return existing
        return self.sudo().create(dict(values, order_id=order.id,
                                       driver_id=driver.id))
