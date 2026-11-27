# -*- coding: utf-8 -*-
"""الوارد الخام من أنظمة التجّار + مُحوّل الصيغ.

لماذا يُحفظ النداء كما وصل:

* **المواصفة تأتي منهم.** العثيم وبندة لا يتبنّون صيغتنا، ولا تصل
  وثيقتهم دائماً - وإن وصلت فهي قديمة أو ناقصة غالباً. النداء الحقيقي
  لا يكذب: نلتقطه، ونكتب المُحوّل من الواقع لا من الورق.
* **يوم الربط** حين يقولون "أرسلنا" ويقال "لم يصلنا"، يُحسم الأمر في
  دقيقة: وصل أم لا، ومتى، وبأي ترويسة، وبأي جسم.
* **لا يضيع طلب.** ما التُقط قبل كتابة المُحوّل يُعاد تحويله بأثر
  رجعي بزر واحد.
"""
import json
import logging
import secrets

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# أقصى حجم جسم نحفظه. أكبر منه يُرفض برمز 413 بدل أن يملأ القاعدة.
MAX_BODY_BYTES = 256 * 1024
# سقف ما يُلتقط لكل تاجر وهو في وضع الالتقاط: حارس ضد نداء مجنون
# يملأ القرص، لا ضد الاستعمال الطبيعي.
CAPTURE_LIMIT = 500
# ترويسات تُخزَّن مقنَّعة: نريد أن نعرف *أي* ترويسة استعملوها وشكلها،
# لا أن نحتفظ بسرّهم نصّاً في سجل يقرأه غير واحد.
SECRET_HEADERS = ('authorization', 'x-api-key', 'apikey', 'x-signature',
                  'signature', 'x-auth-token', 'token', 'cookie')


def _mask(value):
    value = value or ''
    if len(value) <= 6:
        return '***'
    return '%s…%s (%d حرفاً)' % (value[:4], value[-2:], len(value))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    qd_intake_code = fields.Char(
        string='رمز مسار الاستقبال', copy=False, index=True, readonly=True,
        help='الجزء العشوائي في رابط الاستقبال الخاص بهذا التاجر. '
             'الرابط نفسه سرّ، فلا يُخمَّن.')
    qd_intake_url = fields.Char(
        string='رابط الاستقبال', compute='_compute_qd_intake_url',
        help='أعطِ هذا الرابط لنظام التاجر ليدفع عليه الطلبات.')
    qd_capture_mode = fields.Boolean(
        string='وضع الالتقاط (أثناء الربط)', default=True,
        help='مفعّلاً: أي نداء يصل يُحفظ كما وصل ويُرد 202 ولو كانت '
             'صيغته مجهولة - فلا يضيع شيء أثناء الربط.\n'
             'مطفأً: المسار صارم، وصيغة خاطئة ترجع 400 فوراً. '
             'أطفئه بعد انتهاء الربط: قبول طلب لا نفهمه في الإنتاج '
             'يعني طلباً لن يصل أحداً والتاجر يظنّه مقبولاً.')
    qd_payload_format = fields.Selection(
        selection='_qd_payload_format_selection',
        string='صيغة الربط', default='native', required=True,
        help='صيغة الطلب التي يرسلها هذا التاجر. لكل تاجر مُحوّله، '
             'فإضافة الثالث لا تمسّ الاثنين.')
    qd_inbox_count = fields.Integer(
        string='نداءات واردة', compute='_compute_qd_inbox_count')

    @api.model
    def _qd_payload_format_selection(self):
        """نقطة التوسعة: كل تاجر جديد يُضيف سطراً هنا ودالة تحويل.

        لا نخترع صيغاً لم نرها: الصيغة الأصلية وحدها الآن، والبقية
        تُضاف من نداء حقيقي ملتقَط.
        """
        return [('native', 'الصيغة الأصلية (صيغتنا)')]

    @api.depends('qd_intake_code')
    def _compute_qd_intake_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        for rec in self:
            code = rec.sudo().qd_intake_code
            rec.qd_intake_url = ('%s/api/v1/intake/%s' % (base, code)
                                 if code else '')

    def _compute_qd_inbox_count(self):
        Inbox = self.env['quick.delivery.inbox'].sudo()
        groups = Inbox._read_group([('client_id', 'in', self.ids)],
                                   groupby=['client_id'],
                                   aggregates=['__count'])
        counts = {client.id: count for client, count in groups}
        for rec in self:
            rec.qd_inbox_count = counts.get(rec.id, 0)

    _qd_intake_code_uniq = models.Constraint(
        'unique(qd_intake_code)',
        'رمز مسار الاستقبال مستخدم لتاجر آخر بالفعل.',
    )

    def action_qd_generate_intake_code(self):
        """رمز مقروء الأول عشوائي الآخر: يُعطى للتاجر ولا يُخمَّن."""
        for rec in self:
            slug = ''.join(ch for ch in (rec.ref or rec.name or 'merchant')
                           if ch.isalnum() and ch.isascii()).lower()[:12]
            rec.sudo().qd_intake_code = '%s-%s' % (
                slug or 'merchant', secrets.token_urlsafe(9))
        return True

    def action_qd_view_inbox(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'الوارد من %s' % self.name,
            'res_model': 'quick.delivery.inbox',
            'view_mode': 'list,form',
            'domain': [('client_id', '=', self.id)],
        }


class QuickDeliveryInbox(models.Model):
    _name = 'quick.delivery.inbox'
    _description = 'الوارد الخام من نظام التاجر'
    _order = 'id desc'

    client_id = fields.Many2one('res.partner', string='السوبرماركت',
                                index=True, ondelete='cascade')
    endpoint_code = fields.Char(string='رمز المسار', readonly=True)
    received_at = fields.Datetime(string='وقت الوصول', readonly=True,
                                  default=fields.Datetime.now)
    remote_addr = fields.Char(string='من عنوان', readonly=True)
    headers = fields.Json(string='الترويسات', readonly=True)
    raw_body = fields.Text(string='الجسم كما وصل', readonly=True)
    state = fields.Selection([
        ('received', 'وصل - بانتظار التحويل'),
        ('mapped', 'حُوِّل إلى طلب'),
        ('failed', 'تعذّر التحويل'),
    ], string='الحالة', default='received', required=True, index=True)
    error = fields.Text(string='سبب التعذّر', readonly=True)
    attempts = fields.Integer(string='محاولات التحويل', readonly=True,
                              default=0)
    order_id = fields.Many2one('quick.delivery.order', string='الطلب الناتج',
                               readonly=True, ondelete='set null')

    # ------------------------------------------------------------------
    # الالتقاط
    # ------------------------------------------------------------------
    @api.model
    def _qd_capture(self, client, code, raw_body, headers, remote_addr):
        """يحفظ النداء كما وصل - ولو كانت صيغته مجهولة تماماً."""
        if self.sudo().search_count([('client_id', '=', client.id)]) \
                >= CAPTURE_LIMIT:
            # لا نملأ القاعدة بلا حدّ: السقف للالتقاط أثناء الربط،
            # وبعده يُطفأ الوضع أصلاً.
            _logger.warning(
                'سقف الالتقاط (%d) بلغه التاجر %s - النداء لم يُحفظ.',
                CAPTURE_LIMIT, client.name)
            return self.browse()
        return self.sudo().create({
            'client_id': client.id,
            'endpoint_code': code,
            'raw_body': raw_body,
            'headers': headers,
            'remote_addr': remote_addr,
        })

    @api.model
    def _qd_safe_headers(self, headers):
        """الترويسات مع تقنيع الأسرار: نريد *أي* ترويسة وشكلها، لا سرّها."""
        pairs = headers.items() if isinstance(headers, dict) else (headers or ())
        safe = {}
        for key, value in pairs:
            value = str(value)
            safe[key] = (_mask(value) if key.lower() in SECRET_HEADERS
                         else value[:200])
        return safe

    # ------------------------------------------------------------------
    # التحويل
    # ------------------------------------------------------------------
    def _qd_try_map(self):
        """يحاول تحويل الوارد إلى طلب. يُرجع الطلب أو مجموعة فارغة."""
        self.ensure_one()
        Order = self.env['quick.delivery.order'].sudo()
        self.sudo().attempts += 1
        try:
            data = json.loads(self.raw_body or '')
            if not isinstance(data, dict):
                raise ValidationError(_('جسم الطلب ليس كائن JSON.'))
            vals = self._qd_map_payload(self.client_id, data)
            existing = Order.search([
                ('client_id', '=', self.client_id.id),
                ('merchant_order_id', '=', vals['merchant_order_id']),
            ], limit=1)
            # إعادة المعالجة يجب أن تكون آمنة للتكرار: الضغط على الزر
            # مرتين لا ينشئ طلبين.
            order = existing or Order.create(vals)
        except (UserError, ValidationError) as error:
            message = error.args[0] if error.args else _('بيانات غير صالحة')
            self.sudo().write({'state': 'failed', 'error': message})
            return Order.browse()
        except Exception as error:                 # noqa: BLE001
            _logger.exception('تعذّر تحويل الوارد %s', self.id)
            self.sudo().write({'state': 'failed',
                               'error': '%s: %s' % (type(error).__name__,
                                                    error)})
            return Order.browse()
        self.sudo().write({'state': 'mapped', 'error': False,
                           'order_id': order.id})
        return order

    def action_replay(self):
        """إعادة تحويل ما التُقط - بعد كتابة مُحوّل التاجر."""
        mapped = 0
        for rec in self:
            if rec.state == 'mapped':
                continue
            if rec._qd_try_map():
                mapped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('إعادة المعالجة'),
                'message': _('حُوِّل %(ok)d من %(total)d نداء.')
                           % {'ok': mapped, 'total': len(self)},
                'type': 'success' if mapped else 'warning',
            },
        }

    # ------------------------------------------------------------------
    # المُحوّلات
    # ------------------------------------------------------------------
    @api.model
    def _qd_map_payload(self, client, data):
        """يوزّع على مُحوّل التاجر حسب صيغته المعلنة.

        هذه هي النقطة الوحيدة التي تُضاف فيها صيغة تاجر جديد: دالة
        _qd_map_<format> وسطر في _qd_payload_format_selection. لا
        الإسناد ولا تطبيق المندوب ولا المحفظة تتأثر بشيء من ذلك.
        """
        fmt = client.qd_payload_format or 'native'
        handler = getattr(self, '_qd_map_%s' % fmt, None)
        if handler is None:
            raise ValidationError(
                _('لا مُحوّل لصيغة "%s" - أضف دالة _qd_map_%s.')
                % (fmt, fmt))
        vals = handler(client, data)
        vals['client_id'] = client.id
        return vals

    @api.model
    def _qd_map_native(self, client, data):
        """صيغتنا الأصلية - نفس ما يقبله /api/v1/qcommerce/orders."""
        store = data.get('store') or {}
        cust = data.get('customer') or {}
        pay = data.get('payment') or {}

        missing = [name for name, source in (
            ('order_id', data), ('store.store_name', store),
            ('customer.name', cust), ('customer.phone', cust),
        ) if not source.get(name.split('.')[-1])]
        if missing:
            raise ValidationError(_('حقول مطلوبة ناقصة: %s')
                                  % ', '.join(missing))

        method = str(pay.get('method') or 'PREPAID').upper()
        if method not in ('PREPAID', 'COD'):
            raise ValidationError(_('طريقة دفع غير معروفة: %s') % method)
        try:
            sla_minutes = int(data.get('sla_minutes') or 30)
        except (TypeError, ValueError):
            raise ValidationError(_('sla_minutes ليست رقماً'))

        return {
            'merchant_order_id': str(data['order_id']).strip(),
            'sla_minutes': sla_minutes,
            'store_code': store.get('store_code'),
            'store_name': store['store_name'],
            'store_lat': self._qd_coordinate(store.get('lat'), 'store.lat'),
            'store_lng': self._qd_coordinate(store.get('lng'), 'store.lng'),
            'customer_name': cust['name'],
            'customer_phone': cust['phone'],
            'customer_lat': self._qd_coordinate(cust.get('lat'),
                                                'customer.lat'),
            'customer_lng': self._qd_coordinate(cust.get('lng'),
                                                'customer.lng'),
            'address_notes': cust.get('address_notes', ''),
            'bags_count': int(data.get('bags_count') or 1),
            'payment_method': method,
            'cod_amount': (float(pay.get('cod_amount') or 0.0)
                           if method == 'COD' else 0.0),
        }

    @api.model
    def _qd_coordinate(self, value, label):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValidationError(_('قيمة %(field)s ليست رقماً: %(value)r')
                                  % {'field': label, 'value': value})
        if not number:
            raise ValidationError(
                _('قيمة %s مفقودة - لا يمكن الإسناد بلا موقع') % label)
        return number
