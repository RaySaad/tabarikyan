# -*- coding: utf-8 -*-
"""حدّ معدّل الطلبات على المسارات العامة.

المسارات المفتوحة (استقبال التاجر، دخول المندوب) كانت تُستدعى بلا
حدّ: حلقةٌ بسيطة تملأ قاعدتك بالطلبات أو تُجرّب الأرقام السرية بلا
توقّف. ولا يلزم لذلك خصمٌ ماهر - يكفي نظام تاجرٍ معطوب يُعيد المحاولة
في حلقة.

**لماذا في قاعدة البيانات لا في الذاكرة:** أودو تعمل بعدّة عمليات،
وعدّادٌ في ذاكرة كل عملية يعني الحدّ مضروباً في عددها - ويُصفَّر مع
كل إعادة تشغيل. والنافذة هنا مشتركة بين الجميع.

والعدّ بجملة SQL واحدة ذرّية: نداءان متزامنان لا يقرآن العدّاد نفسه
ثم يكتبان فوق بعضهما.
"""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# الحدود الافتراضية (عدد، ثوانٍ). تُضبط من إعدادات النظام بلا كود:
#   quick_delivery.rate_<scope>  =  "عدد/ثوانٍ"  مثل "300/60"
DEFAULTS = {
    # التاجر يُرسل دفعاتٍ في ذروة الغداء: الحدّ واسع عمداً، غرضه
    # إيقاف الحلقة المعطوبة لا تضييق العمل.
    'intake': (300, 60),
    'orders': (300, 60),
    # الدخول: ضيّق. القفل بعد خمس محاولات يحمي مندوباً بعينه، وهذا
    # يحمي من تجريب رقم واحد على ألف رقم.
    'login': (12, 300),
    'driver': (240, 60),
}


class QuickDeliveryThrottle(models.Model):
    _name = 'quick.delivery.throttle'
    _description = 'عدّاد معدّل الطلبات'
    _order = 'id desc'

    scope = fields.Char(string='المسار', required=True, index=True)
    ident = fields.Char(string='المُعرّف', required=True, index=True)
    window_start = fields.Datetime(string='بداية النافذة', required=True)
    hits = fields.Integer(string='عدد النداءات', default=0)
    blocked_hits = fields.Integer(string='نداءات مرفوضة', default=0)

    _scope_ident_uniq = models.Constraint(
        'unique(scope, ident)',
        'عدّاد مكرّر لنفس المسار والمُعرّف.',
    )

    @api.model
    def _qd_limit_for(self, scope):
        """الحدّ من إعدادات النظام، وإلا الافتراضي."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'quick_delivery.rate_%s' % scope, '')
        if raw and '/' in raw:
            try:
                count, seconds = raw.split('/', 1)
                return max(1, int(count)), max(1, int(seconds))
            except (TypeError, ValueError):
                _logger.warning('حدّ معدّل غير صالح لـ%s: %r', scope, raw)
        return DEFAULTS.get(scope, (120, 60))

    @api.model
    def _qd_hit(self, scope, ident):
        """يُسجّل نداءً ويُرجع (مسموح، ثوانٍ حتى تُفتح النافذة).

        جملة واحدة ذرّية: الإدراج أو التحديث، مع تصفير النافذة إن
        انقضت - فلا سباق بين نداءين متزامنين.
        """
        ident = (ident or 'anonymous')[:120]
        limit, window = self._qd_limit_for(scope)
        now = fields.Datetime.now()
        cutoff = fields.Datetime.subtract(now, seconds=window)

        self.env.cr.execute("""
            INSERT INTO quick_delivery_throttle
                (scope, ident, window_start, hits, blocked_hits,
                 create_uid, create_date, write_uid, write_date)
            VALUES (%(scope)s, %(ident)s, %(now)s, 1, 0, 1, %(now)s, 1, %(now)s)
            ON CONFLICT (scope, ident) DO UPDATE SET
                window_start = CASE
                    WHEN quick_delivery_throttle.window_start <= %(cutoff)s
                    THEN %(now)s ELSE quick_delivery_throttle.window_start END,
                hits = CASE
                    WHEN quick_delivery_throttle.window_start <= %(cutoff)s
                    THEN 1 ELSE quick_delivery_throttle.hits + 1 END,
                write_date = %(now)s
            RETURNING hits, window_start
        """, {'scope': scope, 'ident': ident, 'now': now, 'cutoff': cutoff})
        hits, window_start = self.env.cr.fetchone()

        if hits <= limit:
            return True, 0
        self.env.cr.execute("""
            UPDATE quick_delivery_throttle
            SET blocked_hits = blocked_hits + 1
            WHERE scope = %s AND ident = %s
        """, (scope, ident))
        retry_after = max(1, int(
            window - (now - window_start).total_seconds()))
        _logger.warning('تجاوز حدّ المعدّل: %s/%s (%d في %ds)',
                        scope, ident, hits, window)
        return False, retry_after

    @api.model
    def cron_purge(self):
        """عدّادات نوافذ انقضت منذ يوم: لا تُقرأ ولا تُفيد."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        stale = self.search([('window_start', '<', cutoff)], limit=5000)
        count = len(stale)
        stale.unlink()
        if count:
            _logger.info('حُذف %d عدّاد معدّل منقضٍ.', count)
