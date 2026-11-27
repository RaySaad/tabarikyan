# -*- coding: utf-8 -*-
"""إيصال رمز الاستلام إلى جوال العميل - واتساب أولاً ثم رسالة نصية.

**لماذا نُرسله نحن لا التاجر:** الرمز كان يُسلَّم للعثيم مرة واحدة في
رد الـAPI، ثم نعتمد عليهم أن يُوصلوه. وهذه السلسلة تنقطع عند أول تاجر
لا يُنفّذها، فيقف المندوب عند الباب بلا سبيل لإغلاق الطلب إلا الصورة.

**لماذا قناتان:** واتساب يُقرأ أسرع والرابط فيه قابل للضغط، لكن عميلاً
بلا واتساب أو حاجباً لرقمك موجود دائماً، وميتا تردّ بالرفض أحياناً.
فالقنوات مرتّبة، وتُجرَّب واحدة بعد أخرى حتى تنجح واحدة.

**ولماذا لا نستدعي دوال موديول واتساب في أودو:** نقرأ منه بيانات
الاعتماد (فتبقى في مكان واحد تديره من شاشاته) ونُرسل بأنفسنا إلى
واجهة ميتا الموثّقة. استدعاء دالة داخلية يعني أن ترقية أودو التي
تُعيد تسميتها تكسر إرسال الرموز - في مسار الطلبات، لا في شاشة جانبية.
"""
import json
import logging
import re
from datetime import timedelta

import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 15
DEFAULT_GRAPH_VERSION = 'v21.0'

# قوالب جاهزة لمزوّدي الرسائل السعوديين. **تحقّق من وثيقة مزوّدك
# الحالية**: الواجهات تتغيّر، وهذه نقطة بداية لا ضمان. والنوع "عام"
# يعمل مع أي مزوّد بضبط الحقول وحدها.
SMS_PRESETS = {
    'taqnyat': {
        'endpoint_url': 'https://api.taqnyat.sa/v1/messages',
        'headers_json': '{"Authorization": "Bearer {api_key}",'
                        ' "Content-Type": "application/json"}',
        'body_template': '{"recipients": ["{phone}"], "body": "{message}",'
                         ' "sender": "{sender}"}',
    },
    'msegat': {
        'endpoint_url': 'https://www.msegat.com/gw/sendsms.php',
        'headers_json': '{"Content-Type": "application/json"}',
        'body_template': '{"userName": "{sender}", "apiKey": "{api_key}",'
                         ' "numbers": "{phone}", "userSender": "{sender}",'
                         ' "msg": "{message}"}',
    },
    'unifonic': {
        'endpoint_url': 'https://el.cloud.unifonic.com/rest/SMS/messages',
        'headers_json': '{"Content-Type": "application/json"}',
        'body_template': '{"AppSid": "{api_key}", "Recipient": "{phone}",'
                         ' "Body": "{message}", "SenderID": "{sender}"}',
    },
}

DEFAULT_SMS_TEMPLATE = (
    'طلبك من {merchant} في الطريق مع {driver}.\n'
    'رمز الاستلام: {otp}\n'
    'تتبّع: {tracking_url}'
)


def normalize_phone(phone):
    """إلى الصيغة الدولية بلا +: 9665XXXXXXXX.

    المزوّدون وميتا يرفضون 05XXXXXXXX أو يُرسلونها إلى بلد آخر. والعميل
    يُسجّل رقمه كما يحفظه، فالتطبيع هنا لا عنده.
    """
    digits = re.sub(r'\D', '', phone or '')
    if not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0'):
        digits = '966' + digits[1:]
    elif len(digits) == 9 and digits.startswith('5'):
        digits = '966' + digits
    return digits


class QuickDeliveryChannel(models.Model):
    _name = 'quick.delivery.channel'
    _description = 'قناة إبلاغ العميل'
    _order = 'sequence, id'

    name = fields.Char(string='الاسم', required=True)
    active = fields.Boolean(string='مفعّلة', default=True)
    sequence = fields.Integer(
        string='ترتيب المحاولة', default=10,
        help='تُجرَّب القنوات بالترتيب حتى تنجح واحدة. ضع واتساب أولاً '
             'والرسالة النصية بعده.')
    kind = fields.Selection([
        ('whatsapp', 'واتساب (Meta Cloud API)'),
        ('taqnyat', 'رسالة نصية - تقنيات'),
        ('msegat', 'رسالة نصية - مسجات'),
        ('unifonic', 'رسالة نصية - يونيفونك'),
        ('generic', 'رسالة نصية - مزوّد آخر'),
    ], string='النوع', required=True, default='whatsapp')
    is_whatsapp = fields.Boolean(compute='_compute_is_whatsapp')

    # ------------------------------------------------------- واتساب
    wa_account_id = fields.Integer(
        string='حساب واتساب في أودو',
        help='مُعرّف سجل "حساب Whatsapp للأعمال" في أودو. يُقرأ منه رمز '
             'الوصول ومعرّف الرقم، فتبقى بيانات الاعتماد في مكان واحد.')
    wa_account_label = fields.Char(string='الحساب',
                                   compute='_compute_wa_account_label')
    wa_phone_uid = fields.Char(
        string='معرّف الرقم (تجاوز يدوي)',
        groups='quick_delivery.group_qd_manager',
        help='يُستعمل حين لا يكون موديول واتساب مثبّتاً - أو للتجربة.')
    wa_token = fields.Char(
        string='رمز الوصول (تجاوز يدوي)', copy=False,
        groups='quick_delivery.group_qd_manager')
    wa_template_name = fields.Char(
        string='اسم القالب المعتمَد',
        help='اسم القالب كما اعتمدته ميتا بالحرف. الرسالة خارج نافذة '
             'الأربع والعشرين ساعة لا تُرسل إلا بقالب معتمَد.')
    wa_language = fields.Char(string='لغة القالب', default='ar')
    graph_version = fields.Char(
        string='إصدار واجهة ميتا', default=DEFAULT_GRAPH_VERSION,
        help='إصدارات الواجهة تُسحب بعد مدة - يُغيَّر هنا بلا تعديل كود.')

    # -------------------------------------------------- رسالة نصية
    endpoint_url = fields.Char(string='رابط المزوّد')
    api_key = fields.Char(string='مفتاح المزوّد', copy=False,
                          groups='quick_delivery.group_qd_manager')
    sender_name = fields.Char(
        string='اسم المُرسِل',
        help='اسم المُرسِل المعتمد لدى هيئة الاتصالات عبر مزوّدك. '
             'الإرسال باسم غير معتمد يُرفض من الشبكة لا من الكود.')
    headers_json = fields.Text(
        string='الترويسات (JSON)',
        default='{"Content-Type": "application/json"}',
        help='يُستبدل فيها {api_key} و{sender}.')
    body_template = fields.Text(
        string='قالب الجسم',
        help='يُستبدل فيه {phone} و{message} و{sender} و{api_key}.')

    message_template = fields.Text(
        string='نص الرسالة', default=DEFAULT_SMS_TEMPLATE, required=True,
        help='للرسائل النصية: النص كاملاً.\n'
             'لواتساب: ترتيب المتغيّرات في القالب المعتمَد، سطرٌ لكل '
             'متغيّر.\n'
             'المتغيّرات: {otp} {driver} {merchant} {order} {tracking_url} '
             '{cod_amount}')
    test_number = fields.Char(string='رقم للتجربة')

    @api.depends('kind')
    def _compute_is_whatsapp(self):
        for rec in self:
            rec.is_whatsapp = rec.kind == 'whatsapp'

    def _compute_wa_account_label(self):
        Account = self._qd_wa_account_model()
        for rec in self:
            label = ''
            if Account and rec.wa_account_id:
                account = Account.browse(rec.wa_account_id).exists()
                if account:
                    label = '%s (%s)' % (account.name or '',
                                         account.phone_number or '')
            rec.wa_account_label = label or _('غير محدَّد')

    @api.onchange('kind')
    def _onchange_kind(self):
        preset = SMS_PRESETS.get(self.kind)
        if preset:
            self.endpoint_url = preset['endpoint_url']
            self.headers_json = preset['headers_json']
            self.body_template = preset['body_template']

    @api.constrains('headers_json')
    def _check_headers(self):
        for rec in self:
            if rec.kind == 'whatsapp' or not rec.headers_json:
                continue
            try:
                parsed = json.loads(rec.headers_json
                                    .replace('{api_key}', 'x')
                                    .replace('{sender}', 'x'))
            except Exception:
                raise ValidationError(_('الترويسات ليست JSON صالحاً.'))
            if not isinstance(parsed, dict):
                raise ValidationError(_('الترويسات يجب أن تكون كائن JSON.'))

    # ------------------------------------------------------------------
    # بيانات اعتماد واتساب
    # ------------------------------------------------------------------
    @api.model
    def _qd_wa_account_model(self):
        """موديول واتساب من أودو Enterprise قد لا يكون مثبّتاً.

        لا نُعلن عليه اعتماداً: الموديول يجب أن يبقى قابلاً للتثبيت على
        النسخة المجتمعية، والقناة النصية تكفي وحدها.
        """
        if 'whatsapp.account' not in self.env:
            return None
        return self.env['whatsapp.account'].sudo()

    def _qd_wa_credentials(self):
        """(معرّف الرقم، رمز الوصول) - من أودو أو من التجاوز اليدوي."""
        self.ensure_one()
        data = self.sudo()
        Account = self._qd_wa_account_model()
        if Account and data.wa_account_id:
            account = Account.browse(data.wa_account_id).exists()
            if account:
                return account.phone_uid, account.token
        return data.wa_phone_uid, data.wa_token

    # ------------------------------------------------------------------
    # الإرسال
    # ------------------------------------------------------------------
    def _qd_send(self, phone, message):
        """يُرجع (نجح، رمز الاستجابة، تفصيل)."""
        self.ensure_one()
        number = normalize_phone(phone)
        if not number:
            return False, 0, _('رقم جوال غير صالح: %s') % phone
        if self.kind == 'whatsapp':
            return self._qd_send_whatsapp(number, message)
        return self._qd_send_sms(number, message)

    def _qd_send_whatsapp(self, number, message):
        phone_uid, token = self._qd_wa_credentials()
        if not phone_uid or not token:
            return False, 0, _('حساب واتساب غير مضبوط (معرّف الرقم أو '
                               'رمز الوصول ناقص).')
        if not self.wa_template_name:
            return False, 0, _('لا اسم قالب معتمَد.')

        # كل سطر في النص متغيّرٌ في القالب، بترتيبه: {{1}} ثم {{2}}...
        # لأن القالب المعتمَد نصّه ثابت عند ميتا ولا نملك إلا ملء فراغاته.
        parameters = [{'type': 'text', 'text': line}
                      for line in (message or '').split('\n') if line.strip()]
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': number,
            'type': 'template',
            'template': {
                'name': self.wa_template_name,
                'language': {'code': self.wa_language or 'ar'},
                'components': [{'type': 'body',
                                'parameters': parameters}],
            },
        }
        url = 'https://graph.facebook.com/%s/%s/messages' % (
            self.graph_version or DEFAULT_GRAPH_VERSION, phone_uid)
        try:
            response = requests.post(
                url, json=payload,
                headers={'Authorization': 'Bearer %s' % token,
                         'Content-Type': 'application/json'},
                timeout=REQUEST_TIMEOUT)
        except Exception as error:
            return False, 0, str(error)[:250]
        ok = 200 <= response.status_code < 300
        return ok, response.status_code, '' if ok else (response.text or '')[:250]

    def _qd_send_sms(self, number, message):
        data = self.sudo()
        if not self.endpoint_url or not data.api_key:
            return False, 0, _('مزوّد الرسائل غير مضبوط.')
        # النص يمرّ عبر json.dumps ثم تُنزع علاماته: سطر جديد أو علامة
        # اقتباس في رسالة عربية كان يُفسد الـJSON المُرسل.
        safe = json.dumps(message, ensure_ascii=False)[1:-1]
        body = ((self.body_template or '{}')
                .replace('{phone}', number)
                .replace('{message}', safe)
                .replace('{sender}', self.sender_name or '')
                .replace('{api_key}', data.api_key or ''))
        raw_headers = ((self.headers_json or '{}')
                       .replace('{api_key}', data.api_key or '')
                       .replace('{sender}', self.sender_name or ''))
        try:
            headers = json.loads(raw_headers)
        except Exception:
            headers = {'Content-Type': 'application/json'}
        try:
            response = requests.post(self.endpoint_url,
                                     data=body.encode('utf-8'),
                                     headers=headers, timeout=REQUEST_TIMEOUT)
        except Exception as error:
            return False, 0, str(error)[:250]
        # رمز 2xx لا يعني دائماً أن الرسالة أُرسلت: بعض المزوّدين يردّ
        # 200 وفي جسمه خطأ. نحفظ الرد ليُقرأ عند الشك.
        ok = 200 <= response.status_code < 300
        return ok, response.status_code, '' if ok else (response.text or '')[:250]

    def action_send_test(self):
        self.ensure_one()
        if not self.test_number:
            raise UserError(_('اكتب رقماً للتجربة أولاً.'))
        ok, code, error = self._qd_send(
            self.test_number, _('تجربة\nنظام التوصيل\n123456\nبلا رابط'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('نتيجة التجربة'),
                'message': (_('أُرسلت. رمز الاستجابة %s.') % code if ok
                            else _('فشل (%(code)s): %(error)s')
                                 % {'code': code, 'error': error}),
                'sticky': True,
                'type': 'success' if ok else 'danger',
            },
        }


class QuickDeliveryMessage(models.Model):
    """صندوق صادر لرسائل العملاء - يُكتب مع المعاملة ويُرسل بعد تثبيتها.

    رسالةٌ برمز طلبٍ ارتدّت معاملته تُربك العميل ولا يمكن سحبها.
    """
    _name = 'quick.delivery.message'
    _description = 'صادر رسائل العملاء'
    _order = 'id desc'

    order_id = fields.Many2one('quick.delivery.order', string='الطلب',
                               required=True, ondelete='cascade', index=True)
    client_id = fields.Many2one(related='order_id.client_id', store=True,
                                string='السوبرماركت', index=True)
    phone = fields.Char(string='الجوال', required=True)
    body = fields.Text(string='النص', required=True)
    kind = fields.Selection([
        ('otp', 'رمز الاستلام'),
    ], string='النوع', default='otp', required=True, index=True)
    channel_id = fields.Many2one('quick.delivery.channel',
                                 string='القناة التي نجحت', readonly=True)
    state = fields.Selection([
        ('pending', 'بانتظار الإرسال'),
        ('sent', 'أُرسلت'),
        ('failed', 'فشلت نهائياً'),
    ], default='pending', required=True, index=True, string='الحالة')
    attempts = fields.Integer(string='عدد المحاولات', default=0)
    next_attempt_at = fields.Datetime(string='المحاولة القادمة',
                                      default=fields.Datetime.now, index=True)
    last_error = fields.Text(string='آخر خطأ')
    response_code = fields.Integer(string='رمز الاستجابة')
    sent_at = fields.Datetime(string='وقت الإرسال')

    _one_per_kind = models.Constraint(
        'unique(order_id, kind)',
        'أُرسلت رسالة من هذا النوع لهذا الطلب بالفعل.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.cr.postcommit.add(
            lambda ids=records.ids: self._post_commit_flush(ids))
        return records

    @api.model
    def _post_commit_flush(self, ids):
        try:
            self.browse(ids).sudo()._deliver()
        except Exception:
            _logger.exception('فشل إرسال رسائل العملاء بعد التثبيت '
                              '(ids=%s) - سيعيد المجدول المحاولة', ids)

    @api.model
    def cron_flush_pending(self):
        pending = self.search([
            ('state', '=', 'pending'),
            ('next_attempt_at', '<=', fields.Datetime.now()),
        ], order='next_attempt_at asc', limit=50)
        pending._deliver()

    def _deliver(self):
        channels = self.env['quick.delivery.channel'].sudo().search([])
        for record in self:
            if record.state != 'pending':
                continue
            if not channels:
                record.write({'state': 'failed',
                              'last_error': 'لا قناة إبلاغ مضبوطة'})
                continue
            attempts = record.attempts + 1
            errors = []
            for channel in channels:
                ok, code, error = channel._qd_send(record.phone, record.body)
                if ok:
                    record.write({'state': 'sent', 'attempts': attempts,
                                  'channel_id': channel.id,
                                  'response_code': code,
                                  'sent_at': fields.Datetime.now(),
                                  'last_error': False})
                    _logger.info('رسالة الطلب %s أُرسلت عبر %s.',
                                 record.order_id.name, channel.name)
                    break
                # التراجع إلى القناة التالية: عميل بلا واتساب أو حاجب
                # لرقمنا موجود دائماً، والطلب لا ينتظر.
                errors.append('%s: %s' % (channel.name, error or code))
            else:
                exhausted = attempts >= MAX_ATTEMPTS
                record.write({
                    'attempts': attempts,
                    'last_error': ' | '.join(errors)[:900],
                    'state': 'failed' if exhausted else 'pending',
                    'next_attempt_at': fields.Datetime.now() + timedelta(
                        minutes=2 ** min(attempts, 5)),
                })
                log = _logger.error if exhausted else _logger.warning
                log('رسالة الطلب %s: المحاولة %d فشلت على كل القنوات (%s)',
                    record.order_id.name, attempts, ' | '.join(errors)[:200])

    def action_retry(self):
        self.write({'state': 'pending', 'attempts': 0,
                    'next_attempt_at': fields.Datetime.now()})
        self.sudo()._deliver()
        return True
