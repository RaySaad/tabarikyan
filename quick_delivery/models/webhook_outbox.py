# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import requests

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# تراجع أُسّي: 1، 2، 4، 8... دقائق. سيرفر التاجر المتوقّف لا يُقصف
# بمحاولة كل دقيقة، والطلب لا يُنسى.
MAX_ATTEMPTS = 8
REQUEST_TIMEOUT = 10


class QuickDeliveryWebhook(models.Model):
    """صندوق صادر لإبلاغ التاجر - يُكتب مع المعاملة ويُرسل بعد تثبيتها.

    سبب وجوده: الإرسال المباشر داخل write() كان يقع *قبل* تثبيت
    المعاملة (فيُبلَّغ التاجر بتسليم ترتدّ معاملته بعده)، وكان فشله
    يُهمل بصمت بلا سجل ولا إعادة محاولة. هنا السجل أثرٌ دائم: ماذا
    أُرسل، ومتى، وكم محاولة، وآخر خطأ.
    """
    _name = 'quick.delivery.webhook'
    _description = 'صادر إبلاغ التاجر (Webhook)'
    _order = 'id desc'

    order_id = fields.Many2one('quick.delivery.order', string='الطلب',
                               required=True, ondelete='cascade', index=True)
    client_id = fields.Many2one(related='order_id.client_id', store=True,
                                string='السوبرماركت', index=True)
    payload = fields.Json(string='المحتوى المُرسل', required=True)
    state = fields.Selection([
        ('pending', 'بانتظار الإرسال'),
        ('sent', 'تم الإرسال'),
        ('failed', 'فشل نهائياً'),
    ], default='pending', required=True, index=True, string='الحالة')
    attempts = fields.Integer(string='عدد المحاولات', default=0)
    next_attempt_at = fields.Datetime(string='المحاولة القادمة',
                                      default=fields.Datetime.now, index=True)
    last_error = fields.Char(string='آخر خطأ')
    sent_at = fields.Datetime(string='وقت الإرسال')
    response_code = fields.Integer(string='رمز استجابة التاجر')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # محاولة فورية *بعد* تثبيت المعاملة: زمن وصول منخفض بلا الكذب
        # على التاجر. ولو انطفأ الخادم قبل التثبيت، لم يُرسل شيء - وهو
        # المطلوب، لأن تغيير الحالة نفسه لم يُثبَّت.
        self.env.cr.postcommit.add(
            lambda ids=records.ids: self._post_commit_flush(ids))
        return records

    @api.model
    def _post_commit_flush(self, ids):
        """تُنفَّذ بعد الـcommit - بمعاملة جديدة ومعالجة أخطاء كاملة.

        خطأ هنا لا يجوز أن يُسقط طلب HTTP الأصلي (الطلب نُفِّذ وثُبِّت
        بالفعل)، فالتقاط كل شيء مقصود.
        """
        try:
            self.browse(ids).sudo()._deliver()
        except Exception:
            _logger.exception('فشل إرسال إبلاغ التاجر بعد التثبيت (ids=%s) - '
                              'سيعيد المجدول المحاولة', ids)

    @api.model
    def cron_flush_pending(self):
        pending = self.search([
            ('state', '=', 'pending'),
            ('next_attempt_at', '<=', fields.Datetime.now()),
            # حدٌّ منخفض مقصود: كل سجل نداء HTTP بمهلة 10ث، فدفعة كبيرة
            # تُبقي المجدول عالقاً وتؤخّر الإبلاغات الجديدة.
        ], order='next_attempt_at asc', limit=50)
        pending._deliver()

    def _deliver(self):
        for record in self:
            if record.state != 'pending':
                continue
            client = record.order_id.client_id.sudo()
            url = client.webhook_url
            if not url:
                record.write({'state': 'failed',
                              'last_error': 'لا يوجد Webhook URL للعميل'})
                continue
            attempts = record.attempts + 1
            try:
                response = requests.post(
                    url,
                    json=record.payload,
                    headers={'X-Webhook-Secret': client.webhook_secret or '',
                             'X-Delivery-Id': str(record.id)},
                    timeout=REQUEST_TIMEOUT,
                )
                record.response_code = response.status_code
                response.raise_for_status()
            except Exception as error:
                message = str(error)[:250]
                exhausted = attempts >= MAX_ATTEMPTS
                record.write({
                    'attempts': attempts,
                    'last_error': message,
                    'state': 'failed' if exhausted else 'pending',
                    'next_attempt_at': fields.Datetime.now() + timedelta(
                        minutes=2 ** min(attempts, 6)),
                })
                log = _logger.error if exhausted else _logger.warning
                log('إبلاغ التاجر %s للطلب %s: المحاولة %d فشلت (%s)',
                    record.id, record.order_id.name, attempts, message)
                continue
            record.write({'state': 'sent', 'attempts': attempts,
                          'sent_at': fields.Datetime.now(), 'last_error': False})

    def action_retry(self):
        """إعادة محاولة يدوية من غرفة العمليات لما فشل نهائياً."""
        self.write({'state': 'pending', 'attempts': 0,
                    'next_attempt_at': fields.Datetime.now()})
        self.sudo()._deliver()
        return True
