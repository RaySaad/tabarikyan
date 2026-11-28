# -*- coding: utf-8 -*-
"""دفع الإشعارات إلى جوال المندوب والتطبيق مغلق (Web Push).

التنبيه السابق كان تُولّده الصفحة نفسها: تسأل الخادم كل ثماني ثوان،
فإن وجدت طلباً نبّهت. ومعنى ذلك أن التطبيق **إن أُغلق لم يصل شيء** -
لا كود يعمل فلا أحد يسأل. وهذا بالضبط ما شكا منه التشغيل.

هنا يعكس الاتجاه: الخادم يدفع إلى خدمة الدفع في المتصفح (FCM لكروم)،
فتوقظ هي العامل الخدميّ في الجوال ولو كان التطبيق مقفلاً تماماً.

**بلا اعتماد خارجي جديد.** تشفير الحمولة (RFC 8291) وتوقيع VAPID
(RFC 8292) مكتوبان هنا بـcryptography وPyJWT الموجودَين في أودو
أصلاً، بدل pywebpush - فلا ملف requirements.txt في جذر المستودع ولا
مخاطرة في بناء Odoo.sh. والاشتقاق مُختبَر حرفياً على المتجه المرجعي
في RFC 8291 §5 (انظر tests/test_webpush.py).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .outbound_url import OutboundUrlError, check_outbound_url

_logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt
except ImportError:  # pragma: no cover - أودو يجلبها، والحارس للوضوح
    pyjwt = None

PARAM_PRIVATE = 'quick_delivery.vapid_private'
PARAM_PUBLIC = 'quick_delivery.vapid_public'
PARAM_SUBJECT = 'quick_delivery.vapid_subject'

# اثنتا عشرة ساعة: أقصى ما تقبله معظم خدمات الدفع لتوقيع VAPID.
VAPID_TTL = 12 * 3600
# عمر الرسالة في خدمة الدفع إن كان الجوال مغلقاً. طلب توصيل بعد ربع
# ساعة لا قيمة له، فلا نُبقيه ساعات.
MESSAGE_TTL = 900
MAX_ATTEMPTS = 6
RECORD_SIZE = 4096
# حدّ الحمولة بعد التشفير عند معظم الخدمات 4096 بايت. نكتفي بالقليل
# عمداً (انظر _push_payload): لا اسم عميل ولا عنوان على شاشة مقفلة.
MAX_PLAINTEXT = 3000


# ======================================================================
# أدوات ترميز واشتقاق
# ======================================================================
def b64d(value):
    """base64url بلا حشو - كما تُرسله المتصفحات."""
    if isinstance(value, str):
        value = value.encode('ascii')
    return base64.urlsafe_b64decode(value + b'=' * (-len(value) % 4))


def b64e(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _hkdf(salt, ikm, info, length):
    """HKDF-SHA256 لطولٍ لا يتجاوز ٣٢ بايت - وهو كل ما يلزم هنا.

    مكتوبة بالصيغة الحرفية في RFC 8291 §3.4 لا باستدعاء مكتبة: الخطوة
    الواحدة تُقرأ وتُقارن بالنص، والمتجه المرجعي يُثبتها.
    """
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b'\x01', hashlib.sha256).digest()[:length]


def encrypt_payload(payload, p256dh, auth, _salt=None, _as_private=None):
    """يُشفّر الحمولة بصيغة aes128gcm لمفتاح الجهاز (RFC 8291).

    المعاملان الأخيران للاختبار وحده: حقن الملح والمفتاح المؤقّت
    يجعل المتجه المرجعي في RFC 8291 §5 قابلاً للمطابقة حرفياً. وفي
    التشغيل كلاهما عشوائيٌّ لكل رسالة - وإعادة استعمال الملح مع نفس
    المفتاح كسرٌ كامل لـGCM.
    """
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    if len(payload) > MAX_PLAINTEXT:
        raise ValueError('حمولة الدفع أكبر من %d بايت' % MAX_PLAINTEXT)

    ua_public_bytes = b64d(p256dh)
    auth_secret = b64d(auth)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), ua_public_bytes)

    as_private = _as_private or ec.generate_private_key(ec.SECP256R1())
    as_public_bytes = as_private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)

    ecdh_secret = as_private.exchange(ec.ECDH(), ua_public)

    # key_info = "WebPush: info" || 0x00 || ua_public || as_public
    key_info = b'WebPush: info\x00' + ua_public_bytes + as_public_bytes
    ikm = _hkdf(auth_secret, ecdh_secret, key_info, 32)

    salt = _salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)

    # 0x02 فاصل الحشو لآخر سجل. سجلٌ واحد فقط، فلا زيادة على رقم
    # التسلسل في الـnonce.
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)

    header = (salt
              + RECORD_SIZE.to_bytes(4, 'big')
              + bytes([len(as_public_bytes)])
              + as_public_bytes)
    return header + ciphertext


def load_private_key(raw):
    """المفتاح الخاص من صيغة VAPID المعتادة: ٣٢ بايت base64url."""
    return ec.derive_private_key(
        int.from_bytes(b64d(raw), 'big'), ec.SECP256R1())


def generate_keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    private_bytes = private.private_numbers().private_value.to_bytes(32, 'big')
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    return b64e(private_bytes), b64e(public_bytes)


def vapid_headers(endpoint, private_raw, public_raw, subject):
    """ترويسة Authorization بتوقيع ES256 (RFC 8292)."""
    if pyjwt is None:
        raise UserError(_('مكتبة PyJWT غير متاحة - لا يمكن توقيع الدفع.'))
    parts = urlsplit(endpoint)
    claims = {
        'aud': '%s://%s' % (parts.scheme, parts.netloc),
        'exp': int(time.time()) + VAPID_TTL,
        'sub': subject,
    }
    token = pyjwt.encode(claims, load_private_key(private_raw),
                         algorithm='ES256')
    if isinstance(token, bytes):  # PyJWT < 2
        token = token.decode('ascii')
    return {'Authorization': 'vapid t=%s, k=%s' % (token, public_raw)}


# ======================================================================
# المفاتيح
# ======================================================================
class QuickDeliveryPushConfig(models.AbstractModel):
    _name = 'quick.delivery.push.config'
    _description = 'مفاتيح الدفع'

    @api.model
    def _vapid_keys(self):
        """الزوج من معاملات النظام، يُولَّد عند أول حاجة.

        التوليد الكسول لا في بيانات التثبيت: زوجٌ مكتوب في XML يصير
        واحداً لكل من ثبّت الموديول - والمفتاح الخاص سرُّ المثيل.
        """
        Param = self.env['ir.config_parameter'].sudo()
        private = (Param.get_param(PARAM_PRIVATE) or '').strip()
        public = (Param.get_param(PARAM_PUBLIC) or '').strip()
        if not private or not public:
            private, public = generate_keypair()
            Param.set_param(PARAM_PRIVATE, private)
            Param.set_param(PARAM_PUBLIC, public)
            _logger.info('وُلّد زوج مفاتيح VAPID للتوصيل الفوري.')
        return private, public

    @api.model
    def _vapid_public(self):
        return self._vapid_keys()[1]

    @api.model
    def _vapid_subject(self):
        """مُعرِّف المُرسِل لخدمة الدفع: رابط المثيل، لا بريد أحد.

        المواصفة تقبل mailto: أو https:. ورابط المثيل معلومٌ أصلاً
        لخدمة الدفع من الطلب نفسه، فلا نُسرّب به شيئاً جديداً - بخلاف
        بريد شخصيّ يُرسَل إلى طرف ثالث بلا داعٍ.
        """
        Param = self.env['ir.config_parameter'].sudo()
        subject = (Param.get_param(PARAM_SUBJECT) or '').strip()
        if subject:
            return subject
        base = (Param.get_param('web.base.url') or '').strip()
        if base.startswith('https://'):
            return base
        return 'mailto:no-reply@localhost'


# ======================================================================
# اشتراكات الأجهزة
# ======================================================================
class QuickDeliveryPushSubscription(models.Model):
    _name = 'quick.delivery.push.subscription'
    _description = 'جهاز مشترك في إشعارات المندوب'
    _order = 'id desc'

    driver_id = fields.Many2one(
        'quick.delivery.driver', string='المندوب', required=True,
        ondelete='cascade', index=True)
    endpoint = fields.Char(string='نقطة الدفع', required=True, index=True)
    p256dh = fields.Char(string='مفتاح الجهاز', required=True)
    auth = fields.Char(string='سرّ المصادقة', required=True)
    user_agent = fields.Char(string='الجهاز')
    fail_count = fields.Integer(string='إخفاقات متتالية')
    last_error = fields.Char(string='آخر خطأ')
    last_sent_at = fields.Datetime(string='آخر إرسال ناجح')
    active = fields.Boolean(default=True)

    # الجهاز الواحد نقطةٌ واحدة: إعادة فتح التطبيق تُحدِّث ولا تُكرّر،
    # وإلا تراكمت عشرات النقاط الميتة لجوالٍ واحد.
    _endpoint_unique = models.Constraint(
        'unique(endpoint)', 'هذا الجهاز مسجَّل بالفعل.')

    @api.depends('driver_id', 'user_agent')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s — %s' % (
                rec.driver_id.name or '?', (rec.user_agent or 'جهاز')[:40])

    @api.model
    def _register_device(self, driver, endpoint, p256dh, auth,
                         user_agent=''):
        """يُسجّل الجهاز أو ينقله إلى مندوبٍ آخر إن تبدّل حامله.

        الجوال يُسلَّم لمندوبٍ غيره أحياناً. فلو بقيت النقطة معلّقة
        بصاحبها الأول، وصلته طلبات زميله.
        """
        endpoint = (endpoint or '').strip()
        if not endpoint or not p256dh or not auth:
            raise UserError(_('بيانات الاشتراك ناقصة.'))
        # نقطة الدفع يكتبها المتصفح، وجوالٌ مُخترَق قد يكتب عنواناً
        # داخلياً فيجعل الخادم بوّابةً إلى شبكته.
        check_outbound_url(self.env, endpoint, 'نقطة الدفع')

        existing = self.sudo().with_context(active_test=False).search(
            [('endpoint', '=', endpoint)], limit=1)
        values = {
            'driver_id': driver.id,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': (user_agent or '')[:200],
            'fail_count': 0,
            'last_error': False,
            'active': True,
        }
        if existing:
            existing.write(values)
            return existing
        return self.sudo().create(dict(values, endpoint=endpoint))

    def _disable(self, reason):
        """نقطة ماتت عند الخدمة (404/410): تُطفأ ولا تُحذف.

        الحذف يُضيّع أثر "لماذا لم يصل الإشعار" - وهو أول سؤال يُسأل.
        """
        self.sudo().write({'active': False, 'last_error': reason[:200]})
        _logger.info('أُطفئ جهاز دفع للمندوب %s: %s',
                     self.driver_id.name, reason)


# ======================================================================
# صندوق الصادر
# ======================================================================
class QuickDeliveryPush(models.Model):
    _name = 'quick.delivery.push'
    _description = 'صادر إشعارات المندوبين'
    _order = 'id desc'

    order_id = fields.Many2one('quick.delivery.order', string='الطلب',
                               ondelete='cascade', index=True)
    driver_id = fields.Many2one('quick.delivery.driver', string='المندوب',
                                required=True, ondelete='cascade', index=True)
    title = fields.Char(string='العنوان', required=True)
    body = fields.Char(string='النص', required=True)
    url = fields.Char(string='الوجهة')
    kind = fields.Selection([
        ('new_order', 'طلب جديد'),
        ('test', 'تجربة'),
    ], string='النوع', required=True, default='new_order')

    state = fields.Selection([
        ('pending', 'بالانتظار'),
        ('sent', 'أُرسل'),
        ('failed', 'أخفق'),
        ('no_device', 'لا جهاز مسجَّل'),
    ], string='الحالة', default='pending', required=True, index=True)
    attempts = fields.Integer(string='عدد المحاولات')
    next_attempt_at = fields.Datetime(string='المحاولة القادمة',
                                      default=fields.Datetime.now, index=True)
    device_count = fields.Integer(string='أجهزة وصلتها')
    last_error = fields.Text(string='آخر خطأ')
    sent_at = fields.Datetime(string='وقت الإرسال')

    _one_per_order = models.Constraint(
        'unique(order_id, driver_id, kind)',
        'أُرسل إشعار هذا الطلب لهذا المندوب بالفعل.')

    # ------------------------------------------------------------------
    @api.model
    def _enqueue(self, driver, title, body, url=False, order=None,
                 kind='new_order'):
        if not driver:
            return self.browse()
        values = {
            'driver_id': driver.id,
            'order_id': order.id if order else False,
            'title': title,
            'body': body,
            'url': url or False,
            'kind': kind,
        }
        record = self.sudo().create(values)
        # بعد تثبيت المعاملة لا داخلها: نداء شبكة داخل معاملة يُبقي
        # القفل مفتوحاً بقدر بطء الطرف الآخر - والطلب لا يُحفظ أصلاً
        # إن تراجعت المعاملة.
        self.env.cr.postcommit.add(record._deliver_after_commit)
        return record

    def _deliver_after_commit(self):
        """يُشغَّل بعد الـcommit في بيئة جديدة."""
        try:
            with self.pool.cursor() as cr:
                env = self.env(cr=cr)
                env[self._name].browse(self.ids).exists()._deliver()
        except Exception:  # pragma: no cover - المجدول يُعيد المحاولة
            _logger.exception('تعذّر إرسال إشعار الدفع فور الإسناد.')

    @api.model
    def cron_flush_pending(self):
        pending = self.search([
            ('state', '=', 'pending'),
            ('next_attempt_at', '<=', fields.Datetime.now()),
        ], order='next_attempt_at asc', limit=50)
        pending._deliver()

    # ------------------------------------------------------------------
    def _deliver(self):
        Config = self.env['quick.delivery.push.config']
        private, public = Config._vapid_keys()
        subject = Config._vapid_subject()

        for record in self:
            if record.state != 'pending':
                continue
            devices = self.env['quick.delivery.push.subscription'].sudo(
            ).search([('driver_id', '=', record.driver_id.id)])
            if not devices:
                record.write({
                    'state': 'no_device',
                    'last_error': 'لم يُفعّل المندوب الإشعارات على أي جهاز',
                })
                continue

            payload = json.dumps(record._payload(),
                                 ensure_ascii=False).encode('utf-8')
            delivered, errors = 0, []
            for device in devices:
                ok, error = record._send_one(device, payload, private,
                                             public, subject)
                if ok:
                    delivered += 1
                else:
                    errors.append('%s: %s' % (
                        (device.user_agent or 'جهاز')[:30], error))

            attempts = record.attempts + 1
            if delivered:
                record.write({
                    'state': 'sent',
                    'attempts': attempts,
                    'device_count': delivered,
                    'sent_at': fields.Datetime.now(),
                    'last_error': ' | '.join(errors)[:500] or False,
                })
                continue

            exhausted = attempts >= MAX_ATTEMPTS
            record.write({
                'state': 'failed' if exhausted else 'pending',
                'attempts': attempts,
                'last_error': ' | '.join(errors)[:500],
                'next_attempt_at': fields.Datetime.now() + timedelta(
                    seconds=15 * (2 ** min(attempts, 5))),
            })
            _logger.warning('إشعار المندوب %s للطلب %s أخفق (محاولة %d): %s',
                            record.driver_id.name,
                            record.order_id.name or '-', attempts,
                            ' | '.join(errors)[:200])

    def _payload(self):
        self.ensure_one()
        return {
            'title': self.title,
            'body': self.body,
            'url': self.url or '/driver',
            'tag': 'qd-order',
            'order_id': self.order_id.id or 0,
        }

    def _send_one(self, device, payload, private, public, subject):
        """يُرسل إلى جهازٍ واحد. يُرجع (نجح، سبب الإخفاق)."""
        self.ensure_one()
        try:
            check_outbound_url(self.env, device.endpoint, 'نقطة الدفع')
        except OutboundUrlError as error:
            device._disable(str(error))
            return False, str(error)

        try:
            body = encrypt_payload(payload, device.p256dh, device.auth)
            headers = vapid_headers(device.endpoint, private, public, subject)
        except Exception as error:
            # مفتاح جهازٍ تالف لا يُصلحه التكرار.
            device._disable('تعذّر التشفير: %s' % error)
            return False, 'تعذّر التشفير: %s' % error

        headers.update({
            'Content-Encoding': 'aes128gcm',
            'Content-Type': 'application/octet-stream',
            'TTL': str(MESSAGE_TTL),
            'Urgency': 'high',
        })
        try:
            response = requests.post(device.endpoint, data=body,
                                     headers=headers, timeout=10)
        except requests.RequestException as error:
            device.sudo().write({
                'fail_count': device.fail_count + 1,
                'last_error': str(error)[:200],
            })
            return False, str(error)

        if response.status_code in (404, 410):
            device._disable('ألغى الجهاز اشتراكه (%d)' % response.status_code)
            return False, 'اشتراك منتهٍ (%d)' % response.status_code
        if response.status_code >= 400:
            device.sudo().write({
                'fail_count': device.fail_count + 1,
                'last_error': 'HTTP %d' % response.status_code,
            })
            return False, 'HTTP %d %s' % (response.status_code,
                                          (response.text or '')[:120])

        device.sudo().write({
            'fail_count': 0,
            'last_error': False,
            'last_sent_at': fields.Datetime.now(),
        })
        return True, ''

    def action_retry(self):
        self.write({'state': 'pending', 'attempts': 0,
                    'next_attempt_at': fields.Datetime.now()})
        self._deliver()


# ======================================================================
# على بطاقة المندوب
# ======================================================================
class QuickDeliveryDriver(models.Model):
    _inherit = 'quick.delivery.driver'

    push_subscription_ids = fields.One2many(
        'quick.delivery.push.subscription', 'driver_id',
        string='أجهزة الإشعارات')
    push_device_count = fields.Integer(
        string='أجهزة تصلها الإشعارات',
        compute='_compute_push_device_count')

    @api.depends('push_subscription_ids.active')
    def _compute_push_device_count(self):
        for rec in self:
            rec.push_device_count = len(rec.push_subscription_ids)

    def action_qd_test_push(self):
        """يُرسل إشعاراً تجريبياً الآن - لا ينتظر طلباً.

        السؤال "هل فعّل المندوب الإشعارات؟" يُجاب بالتجربة لا
        بالتخمين، قبل أن يضيع طلبٌ حقيقي.
        """
        self.ensure_one()
        if not self.push_subscription_ids:
            raise UserError(_(
                'لم يُفعّل %s الإشعارات على أي جهاز بعد. يفتح التطبيق '
                'ويسمح بالإشعارات، ثم أعد المحاولة.') % self.name)
        Push = self.env['quick.delivery.push'].sudo()
        record = Push.create({
            'driver_id': self.id,
            'title': _('تجربة إشعار'),
            'body': _('وصلك هذا الإشعار - التنبيهات تعمل.'),
            'url': '/driver',
            'kind': 'test',
        })
        record._deliver()
        if record.state == 'sent':
            message = _('أُرسل إلى %d جهاز.') % record.device_count
            kind = 'success'
        else:
            message = record.last_error or _('لم يصل.')
            kind = 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('تجربة الإشعار'), 'message': message,
                       'type': kind, 'sticky': kind == 'danger'},
        }
