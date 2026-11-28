# -*- coding: utf-8 -*-
import base64
import logging
import re
import math
import secrets
from datetime import timedelta

import pytz
from passlib.context import CryptContext

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# نطاق البحث الافتراضي عن مندوب (كم). يُقرأ من إعدادات النظام
# (quick_delivery.dispatch_radius_km) ليُعدَّل بلا تعديل كود.
DEFAULT_DISPATCH_RADIUS_KM = 6.0

# حدّ محاولات رمز التسليم على الطلب الواحد. بعده لا يُغلق إلا بصورة.
MAX_OTP_ATTEMPTS = 5

# بصمة مفاتيح الـAPI. دورات مخفّضة عمداً: المفتاح عشوائي بإنتروبيا
# عالية (32 بايت) فلا يُهاجَم بالقاموس، وهذه الدالة تُنفَّذ في **كل**
# طلب يصل من التاجر - التكلفة الكاملة تُضيف عشرات الأجزاء من الثانية
# إلى كل طلب بلا فائدة أمنية. وهو نفس ما تفعله أودو لمفاتيح واجهتها.
API_KEY_CRYPT = CryptContext(['pbkdf2_sha512'], pbkdf2_sha512__rounds=6000)
API_KEY_INDEX_SIZE = 10
API_KEY_MIN_LENGTH = 24

# المنطقة الزمنية التي تُحسب عليها "أيام" العمل (عهدة اليوم، أرباح اليوم).
# الافتراضي الرياض: الخطأ هنا خطأ مالي، لا تجميلي - يوم الرياض يبدأ
# 21:00 UTC من اليوم السابق، فحساب "اليوم" بـ UTC ينقل أول ثلاث ساعات
# من كل يوم سعودي إلى اليوم الذي قبله.
FALLBACK_TZ = 'Asia/Riyadh'


def _day_start_utc(env, reference=None):
    """بداية "اليوم" المحلي معبَّراً عنها بـ UTC ساذج (كما تُخزّن أودو).

    الترتيب: منطقة المستخدم، ثم منطقة السياق، ثم الرياض. لا نقرأ تقويم
    عمل الشركة: resource_calendar_id ليس في res.company الأساسي (يأتي
    من موديول resource)، فقراءته تُسقط الحساب على تثبيت بلا ذلك
    الموديول - والموديول هنا لا يعتمد عليه.
    """
    tz_name = env.user.tz or env.context.get('tz') or FALLBACK_TZ
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:          # pragma: no cover - إعداد خاطئ
        _logger.warning('منطقة زمنية غير معروفة %s - نرجع إلى %s',
                        tz_name, FALLBACK_TZ)
        tz = pytz.timezone(FALLBACK_TZ)
    now_utc = pytz.utc.localize(reference or fields.Datetime.now())
    local_midnight = now_utc.astimezone(tz).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(pytz.utc).replace(tzinfo=None)


def _month_start_utc(env, reference=None):
    """بداية الشهر المحلي - بنفس منطقة اليوم، لا بـUTC."""
    day_start = _day_start_utc(env, reference)
    tz_name = env.user.tz or env.context.get('tz') or FALLBACK_TZ
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:          # pragma: no cover
        tz = pytz.timezone(FALLBACK_TZ)
    local = pytz.utc.localize(day_start).astimezone(tz).replace(day=1)
    return local.astimezone(pytz.utc).replace(tzinfo=None)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_qcommerce_client = fields.Boolean(string='عميل توصيل فوري (سوبرماركت)')
    # مفاتيح الـAPI وسرّ الـWebhook ورابطه: محصورة بمجموعة المدير على
    # مستوى *الحقل* نفسه، لا بإخفائها في العرض وحده. إخفاء العرض يبقي
    # الحقل مقروءاً ومكتوباً عبر RPC أو الاستيراد أو التعديل الجماعي -
    # ورابط الـWebhook المكتوب من أي مستخدم داخلي يحوّل بيانات كل
    # الطلبات (اسم العميل وجواله وموقعه) إلى أي سيرفر يختاره.
    # المفتاح يُخزَّن مُعمّى لا نصّاً: نسخة من قاعدة البيانات أو من
    # نسخة احتياطية كانت تعطي مفاتيح العثيم وبندة جاهزةً لإرسال طلبات
    # باسمهم. والبحث بالبادئة ثم تحقّق البصمة - كما تفعل أودو
    # لمفاتيح واجهتها (res.users.apikeys).
    api_key = fields.Char(
        string='API Key', compute='_compute_api_key',
        inverse='_inverse_api_key', groups='quick_delivery.group_qd_manager',
        help='يُعرض فارغاً دائماً: المخزَّن بصمته لا نصّه. '
             'اضغط "توليد مفتاح جديد" وانسخه حينها - لن يُعرض ثانيةً.')
    api_key_index = fields.Char(
        string='بادئة المفتاح', copy=False, index=True,
        groups='quick_delivery.group_qd_manager')
    api_key_hash = fields.Char(
        string='بصمة المفتاح', copy=False,
        groups='quick_delivery.group_qd_manager')
    has_api_key = fields.Boolean(
        string='له مفتاح API', compute='_compute_has_api_key',
        compute_sudo=True, search='_search_has_api_key')
    webhook_url = fields.Char(
        string='Webhook URL', groups='quick_delivery.group_qd_manager')
    webhook_secret = fields.Char(
        string='Webhook Secret', groups='quick_delivery.group_qd_manager')
    delivery_fee_per_order = fields.Float(
        string='رسوم التوصيل للطلب (SAR)', default=12.0,
        groups='quick_delivery.group_qd_manager')
    qd_sms_customer = fields.Boolean(
        string='أرسل رمز الاستلام لعميله', default=True,
        help='رسالة نصية تحمل الرمز ورابط التتبّع، تُرسل عند إسناد '
             'المندوب. أطفئها لمن يُوصل الرمز بنفسه - لكل رسالة تكلفة.')

    # أرقام الشهر لكل سوبرماركت: مع عميل واحد كانت القائمة تكفي، ومع
    # العثيم وبندة وغيرهما لا تكفي - تحتاج "كم طلباً وكم رسماً لكلٍّ".
    qd_month_orders = fields.Integer(
        string='طلبات الشهر', compute='_compute_qd_month_figures',
        compute_sudo=True)
    qd_month_fees = fields.Float(
        string='رسوم الشهر (SAR)', compute='_compute_qd_month_figures',
        compute_sudo=True,
        help='مجموع الرسوم المثبَّتة على طلبات الشهر المسلَّمة - بالرسم '
             'الذي كان ساريا وقت كل طلب، لا بالرسم الحالي.')
    # الأرقام الحيّة لكل سوبرماركت: الكروت تعرضها، فتُقرأ حالة كل
    # شركة من نظرة واحدة بدل فتح قائمة وفلترتها.
    qd_dedicated_driver_ids = fields.Many2many(
        'quick.delivery.driver', 'qd_driver_client_rel', 'client_id',
        'driver_id', string='المندوبون المخصَّصون',
        help='من خُصّص لهذه الشركة وحدها. فارغ = كل المندوبين يخدمونها.')
    qd_active_orders = fields.Integer(
        string='طلبات جارية', compute='_compute_qd_live_figures',
        compute_sudo=True)
    qd_late_orders = fields.Integer(
        string='متأخرة الآن', compute='_compute_qd_live_figures',
        compute_sudo=True)
    qd_today_delivered = fields.Integer(
        string='سُلّمت اليوم', compute='_compute_qd_live_figures',
        compute_sudo=True)
    qd_is_configured = fields.Boolean(
        string='الربط مكتمل', compute='_compute_qd_is_configured',
        search='_search_qd_is_configured', compute_sudo=True,
        help='له مفتاح API ورابط إبلاغ - أي يستطيع إرسال الطلبات '
             'واستقبال تغيّر الحالة.')

    def _compute_api_key(self):
        """لا يُقرأ أبداً: المخزَّن بصمةٌ لا نصّ."""
        for rec in self:
            rec.api_key = ''

    def _inverse_api_key(self):
        for rec in self:
            value = (rec.api_key or '').strip()
            if not value:
                continue
            if len(value) < API_KEY_MIN_LENGTH:
                raise ValidationError(_(
                    'مفتاح الـAPI قصير (%(len)d حرفاً). الحدّ الأدنى '
                    '%(min)d - أو اضغط "توليد مفتاح جديد".'
                ) % {'len': len(value), 'min': API_KEY_MIN_LENGTH})
            rec.sudo().write({
                'api_key_index': self._qd_api_key_index(value),
                'api_key_hash': self._qd_api_key_hash(value),
            })

    @api.depends('api_key_hash')
    def _compute_has_api_key(self):
        for rec in self:
            rec.has_api_key = bool(rec.sudo().api_key_hash)

    def _search_has_api_key(self, operator, value):
        if operator not in ('in', 'not in'):
            raise NotImplementedError(operator)
        wanted = True in value
        if operator == 'not in':
            wanted = not wanted
        return [('api_key_hash', '!=' if wanted else '=', False)]

    @api.model
    def _qd_api_key_index(self, key):
        return (key or '').strip()[:API_KEY_INDEX_SIZE]

    @api.model
    def _qd_api_key_hash(self, key):
        return API_KEY_CRYPT.hash((key or '').strip())

    @api.model
    def _qd_client_from_api_key(self, key):
        """التاجر من مفتاحه - بالبادئة ثم تحقّق البصمة.

        البحث بالبادئة يُضيّق المرشّحين إلى واحد عملياً، فلا نتحقّق من
        بصمة كل عميل في كل طلب.
        """
        key = (key or '').strip()
        if len(key) < API_KEY_MIN_LENGTH:
            return self.browse()
        candidates = self.sudo().search([
            ('api_key_index', '=', key[:API_KEY_INDEX_SIZE]),
            ('is_qcommerce_client', '=', True),
        ])
        for client in candidates:
            stored = client.api_key_hash
            if stored and API_KEY_CRYPT.verify(key, stored):
                return client
        return self.browse()

    def action_qd_generate_api_key(self):
        """مفتاح جديد يُعرض مرة واحدة - والقديم يبطل فوراً."""
        self.ensure_one()
        new_key = secrets.token_urlsafe(32)
        self.api_key = new_key
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('مفتاح API جديد لـ%s') % self.name,
                'message': _(
                    '%(key)s\n\nانسخه الآن وأعطه للتاجر: لن يُعرض مرة '
                    'أخرى، والمخزَّن بصمته لا نصّه. والمفتاح القديم '
                    'بطل - نظامهم سيُرفض حتى تعطيهم الجديد.'
                ) % {'key': new_key},
                'sticky': True,
                'type': 'warning',
            },
        }

    @api.depends('api_key_hash', 'webhook_url')
    def _compute_qd_is_configured(self):
        # على البصمة لا على المفتاح: المفتاح صار حقلاً محسوباً يُقرأ
        # فارغاً دائماً، فالاعتماد عليه كان يجعل كل تاجر "ربطه ناقص".
        for rec in self:
            data = rec.sudo()
            rec.qd_is_configured = bool(data.api_key_hash
                                        and data.webhook_url)

    def _search_qd_is_configured(self, operator, value):
        """محسوب غير مخزَّن لا يُبحث فيه بلا هذه الدالة - والفلتر
        المطلوب هو "من ربطه ناقص" قبل أن يُرسل أول طلب."""
        if operator not in ('in', 'not in'):
            raise NotImplementedError(operator)
        wanted = True in value
        if operator == 'not in':
            wanted = not wanted
        ready = ['&', ('api_key_hash', '!=', False),
                 ('webhook_url', '!=', False)]
        if wanted:
            return ready
        return ['!'] + ready

    def _compute_qd_live_figures(self):
        """ثلاثة استعلامات مُجمَّعة للقائمة كلها، لا ثلاثة لكل كرت."""
        Order = self.env['quick.delivery.order'].sudo()
        now = fields.Datetime.now()
        day_start = _day_start_utc(self.env)

        def by_client(domain):
            return {client.id: count for client, count in Order._read_group(
                domain + [('client_id', 'in', self.ids)],
                groupby=['client_id'], aggregates=['__count'])}

        active = by_client([('state', 'in', Order.OPEN_STATES)])
        late = by_client([('state', 'in', Order.OPEN_STATES),
                          ('sla_deadline', '<', now)])
        done = by_client([('state', '=', 'delivered'),
                          ('delivered_at', '>=', day_start)])
        for rec in self:
            rec.qd_active_orders = active.get(rec.id, 0)
            rec.qd_late_orders = late.get(rec.id, 0)
            rec.qd_today_delivered = done.get(rec.id, 0)

    def action_qd_view_live_orders(self):
        self.ensure_one()
        Order = self.env['quick.delivery.order']
        return {
            'type': 'ir.actions.act_window',
            'name': 'الطلبات الجارية - %s' % self.name,
            'res_model': 'quick.delivery.order',
            'view_mode': 'list,form',
            'domain': [('client_id', '=', self.id),
                       ('state', 'in', list(Order.OPEN_STATES))],
        }

    def _compute_qd_month_figures(self):
        """استعلامان مُجمَّعان للقائمة كلها، لا استعلام لكل سطر."""
        Order = self.env['quick.delivery.order'].sudo()
        month_start = _month_start_utc(self.env)
        domain = [('client_id', 'in', self.ids), ('state', '=', 'delivered'),
                  ('delivered_at', '>=', month_start)]
        groups = Order._read_group(
            domain, groupby=['client_id'],
            aggregates=['__count', 'delivery_fee:sum'])
        by_client = {client.id: (count, fees)
                     for client, count, fees in groups}
        for rec in self:
            count, fees = by_client.get(rec.id, (0, 0.0))
            rec.qd_month_orders = count
            rec.qd_month_fees = fees

    def action_qd_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'طلبات %s' % self.name,
            'res_model': 'quick.delivery.order',
            'view_mode': 'list,form',
            'domain': [('client_id', '=', self.id)],
            'context': {'search_default_group_state': 1},
        }


class QuickDeliveryOrder(models.Model):
    _name = 'quick.delivery.order'
    _description = 'طلب توصيل فوري (30 دقيقة)'
    _order = 'sla_deadline asc, id desc'

    # الحالات التي يكون الطلب فيها "حياً" - أي يشغل مندوباً.
    OPEN_STATES = ('searching_driver', 'driver_assigned',
                   'arrived_at_store', 'picked_up')
    # آلة الحالات: انتقال غير مذكور هنا مرفوض. النسخة السابقة كانت تكتب
    # أي نص يرسله التطبيق مباشرةً في state - فيقفز المندوب من "تم
    # التعيين" إلى "تم التسليم" بلا استلام، أو يعيد طلباً مسلَّماً إلى
    # الطريق.
    ALLOWED_TRANSITIONS = {
        'searching_driver': ('driver_assigned', 'cancelled'),
        'driver_assigned': ('arrived_at_store', 'picked_up', 'failed',
                            'cancelled', 'searching_driver'),
        'arrived_at_store': ('picked_up', 'failed', 'cancelled'),
        'picked_up': ('delivered', 'failed'),
        'delivered': (),
        'failed': (),
        'cancelled': (),
    }

    name = fields.Char(string='رقم التتبع', required=True, copy=False,
                       readonly=True, default='New', index=True)
    client_id = fields.Many2one('res.partner', string='الشركة / السوبرماركت',
                                required=True, index=True, ondelete='restrict')
    merchant_order_id = fields.Char(string='رقم طلب التاجر', required=True,
                                    index=True)

    # Store Pickup
    store_code = fields.Char(string='كود الفرع')
    store_name = fields.Char(string='اسم الفرع', required=True)
    store_lat = fields.Float(string='Lat الفرع', digits=(10, 7), required=True)
    store_lng = fields.Float(string='Lng الفرع', digits=(10, 7), required=True)

    # Customer Delivery
    customer_name = fields.Char(string='اسم العميل', required=True)
    customer_phone = fields.Char(string='جوال العميل', required=True)
    customer_lat = fields.Float(string='Lat العميل', digits=(10, 7),
                                required=True)
    customer_lng = fields.Float(string='Lng العميل', digits=(10, 7),
                                required=True)
    address_notes = fields.Text(string='وصف العنوان')

    # Financials & Bags
    bags_count = fields.Integer(string='عدد الأكياس', default=1)
    payment_method = fields.Selection([
        ('PREPAID', 'مدفوع مسبقاً'),
        ('COD', 'دفع عند الاستلام')
    ], default='PREPAID', string='طريقة الدفع', required=True)
    cod_amount = fields.Float(string='مبلغ التحصيل (SAR)', default=0.0)
    # الرسم والعمولة يُثبَّتان على الطلب لا يُقرآن من الإعداد الحالي:
    # رفعُ رسم العثيم من 12 إلى 15 كان يُعيد كتابة كل تقرير سابق
    # بأثر رجعي، فيصير حساب الشهر الماضي رقماً لم يُتَّفق عليه.
    delivery_fee = fields.Float(
        string='رسم التوصيل المحتسب (SAR)', readonly=True, copy=False,
        help='رسم السوبرماركت كما كان وقت إنشاء الطلب.')
    driver_commission = fields.Float(
        string='عمولة المندوب المحتسبة (SAR)', readonly=True, copy=False,
        help='عمولة المندوب كما كانت وقت إسناد الطلب إليه.')
    net_revenue = fields.Float(
        string='الصافي (SAR)', compute='_compute_net_revenue', store=True,
        help='رسم التوصيل ناقص عمولة المندوب.')
    is_cod_settled = fields.Boolean(string='تمت تسوية العهدة', default=False)
    cod_settled_at = fields.Datetime(string='تاريخ تسوية العهدة')

    # Proof of Delivery (OTP & Photo)
    # الرمز محصور بمجموعة المدير: المندوب يُدخله ولا يقرأه (المقارنة في
    # الخادم بـsudo)، وغرفة العمليات لا تحتاجه - ومن يقرأه يستطيع إغلاق
    # أي طلب بلا تسليم.
    # رابط التتبع للعميل النهائي: رمز عشوائي طويل هو الحارس الوحيد.
    # لا رقم تسلسلي: QCK-2026-000047 يُخمَّن، فيقرأ أي أحد رمز تسليم
    # أي طلب ويستلم بدل صاحبه.
    tracking_token = fields.Char(
        string='رمز رابط التتبع', copy=False, index=True, readonly=True)
    tracking_url = fields.Char(
        string='رابط تتبع العميل', compute='_compute_tracking_url',
        help='يُعطى للعميل النهائي: يرى حالة طلبه ومندوبه ورمز التسليم.')
    delivery_otp = fields.Char(string='رمز التحقق (OTP)', copy=False,
                               groups='quick_delivery.group_qd_manager')
    # عدد محاولات الرمز: ستة أرقام تُخمَّن بالتكرار، ولم يكن ثمة حدٌّ
    # ولا أثرٌ لمن يحاول. المندوب قد يُغلق طلباً بلا تسليم.
    otp_attempts = fields.Integer(string='محاولات الرمز الخاطئة',
                                  readonly=True, copy=False)
    pod_photo = fields.Binary(string='صورة إثبات التسليم', attachment=True)
    pod_method = fields.Selection([
        ('otp', 'رمز تحقق من العميل'),
        ('photo', 'صورة عند الباب'),
    ], string='طريقة إثبات التسليم', readonly=True, copy=False,
        help='يُسجَّل تلقائياً عند الإغلاق - التسليم بصورة وحدها أضعف من '
             'الرمز، فيجب أن يكون قابلاً للفرز والمراجعة.')

    # Failure / Cancellation Reason
    failure_reason = fields.Selection([
        ('customer_no_answer', 'العميل لا يرد على الاتصال'),
        ('wrong_address', 'العنوان أو الموقع غير صحيح'),
        ('customer_refused', 'العميل رفض استلام الطلب'),
        ('store_delayed', 'تأخر تجهيز الطلب في السوبرماركت'),
        ('cancelled_by_merchant', 'ملغي من قبل التاجر')
    ], string='سبب تعذر التسليم / الإلغاء')
    failure_notes = fields.Char(string='ملاحظات التعذر')

    # SLA 30-Min Timer
    sla_minutes = fields.Integer(string='مدة التوصيل المستهدفة (دقيقة)',
                                 default=30)
    sla_deadline = fields.Datetime(string='الحد الأقصى للتسليم',
                                   compute='_compute_deadline', store=True)
    delivered_at = fields.Datetime(string='وقت التسليم الفعلي')

    # Dispatch & State
    # المندوب كيان مستقل لا مستخدم أودو: لا رخصة مدفوعة لكل مندوب، ولا
    # دخول إلى /web من جوال يُسلَّم لغيره غداً. ondelete='restrict'
    # لأن حذف المندوب يمسح تاريخ من أوصل ماذا - الأرشفة هي الطريق.
    # لماذا لم يُسنَد: كان الطلب يجلس في "جاري البحث" بلا سبب مكتوب،
    # فيُخمَّن: أبعيد؟ أمشغول؟ أمنصرف؟ وكلٌّ منها يستدعي قراراً مختلفاً
    # (نطاق أوسع، أو مندوب إضافي، أو تنبيههم ليفتحوا التطبيق).
    dispatch_note = fields.Char(string='سبب عدم الإسناد', readonly=True,
                                copy=False)
    driver_id = fields.Many2one('quick.delivery.driver',
                                string='المندوب المسند', index=True,
                                ondelete='restrict')
    # قياس زمن الوصول: متى أُسند، ومتى علم به جوال المندوب فعلاً.
    # بلا هذين الرقمين يبقى السؤال "هل الإشعار يصل؟" رأياً يتبادله
    # الناس - ومعهما يصير جدولاً يُقرأ قبل شراء تطبيقٍ أصلي.
    assigned_at = fields.Datetime(string='وقت الإسناد', readonly=True,
                                  copy=False)
    driver_seen_at = fields.Datetime(string='علم به المندوب', readonly=True,
                                     copy=False)
    notify_seconds = fields.Integer(
        string='ثوانٍ حتى علم المندوب', compute='_compute_notify_seconds',
        store=True, readonly=True,
        help='الفرق بين الإسناد وأول مرة ظهر فيها الطلب على جواله.')
    state = fields.Selection([
        ('searching_driver', 'جاري البحث عن مندوب'),
        ('driver_assigned', 'تم تعيين مندوب'),
        ('arrived_at_store', 'المندوب في الفرع'),
        ('picked_up', 'تم الاستلام - في الطريق'),
        ('delivered', 'تم التسليم'),
        ('failed', 'تعذر التسليم'),
        ('cancelled', 'ملغي')
    ], default='searching_driver', string='الحالة', required=True, index=True)

    # قيد قاعدة بيانات، لا فحصٌ في الكود: فحص التكرار في الـAPI بحثٌ ثم
    # إنشاء، ونداءان متزامنان بنفس رقم الطلب يمرّان كلاهما من الفحص
    # فيُنشأ طلبان لنفس الطلب (ومندوبان، ورسمان).
    _merchant_order_uniq = models.Constraint(
        'unique(client_id, merchant_order_id)',
        'رقم الطلب هذا مسجَّل لنفس السوبرماركت بالفعل.',
    )

    # ------------------------------------------------------------------
    # قيود البيانات
    # ------------------------------------------------------------------
    @api.constrains('store_lat', 'store_lng', 'customer_lat', 'customer_lng')
    def _check_coordinates(self):
        """إحداثيات (0,0) تعني "لم تُرسل" - وكانت تُقبل صامتةً فيصير الفرع
        في خليج غينيا، ويفشل كل إسناد إلى الأبد بلا رسالة خطأ واحدة."""
        for rec in self:
            for lat, lng, label in (
                (rec.store_lat, rec.store_lng, 'الفرع'),
                (rec.customer_lat, rec.customer_lng, 'العميل'),
            ):
                if not lat or not lng:
                    raise ValidationError(_(
                        'إحداثيات %s مفقودة - لا يمكن إسناد مندوب بلا موقع.'
                    ) % label)
                if not -90.0 <= lat <= 90.0 or not -180.0 <= lng <= 180.0:
                    raise ValidationError(_(
                        'إحداثيات %s خارج النطاق الصحيح (lat=%s, lng=%s).'
                    ) % (label, lat, lng))

    @api.constrains('payment_method', 'cod_amount')
    def _check_cod_amount(self):
        for rec in self:
            if rec.payment_method == 'COD' and rec.cod_amount <= 0:
                raise ValidationError(_(
                    'طلب "دفع عند الاستلام" بمبلغ تحصيل صفر - المبلغ مطلوب، '
                    'وإلا خرجت عهدة المندوب ناقصة.'))
            if rec.payment_method == 'PREPAID' and rec.cod_amount:
                raise ValidationError(_(
                    'طلب مدفوع مسبقاً بمبلغ تحصيل %s - لا يُحصَّل منه شيء.'
                ) % rec.cod_amount)

    @api.constrains('sla_minutes')
    def _check_sla_minutes(self):
        for rec in self:
            if rec.sla_minutes <= 0:
                raise ValidationError(_('مدة التوصيل المستهدفة يجب أن تكون '
                                        'أكبر من صفر.'))

    @api.depends('tracking_token')
    def _compute_tracking_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        for rec in self:
            token = rec.sudo().tracking_token
            rec.tracking_url = '%s/track/%s' % (base, token) if token else ''

    @api.depends('delivery_fee', 'driver_commission')
    def _compute_net_revenue(self):
        for rec in self:
            rec.net_revenue = rec.delivery_fee - rec.driver_commission

    @api.depends('create_date', 'sla_minutes')
    def _compute_deadline(self):
        for rec in self:
            base_time = rec.create_date or fields.Datetime.now()
            rec.sla_deadline = base_time + timedelta(minutes=rec.sla_minutes)

    # ------------------------------------------------------------------
    # الإنشاء والكتابة
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'quick.delivery.order'
                ) or 'QCK-%s' % fields.Datetime.now().strftime('%Y%m%d%H%M%S%f')
        records = super().create(vals_list)
        for rec in records:
            if not rec.delivery_fee:
                rec.sudo().delivery_fee = \
                    rec.client_id.sudo().delivery_fee_per_order
            # الرمز يُكتب بـsudo بعد الإنشاء، لا في vals: الحقل محصور
            # بمجموعة المدير، فكتابته في vals تمنع غرفة العمليات من
            # إنشاء طلب يدوياً بخطأ صلاحية.
            if not rec.sudo().delivery_otp:
                rec.sudo().delivery_otp = self._generate_otp()
            if not rec.sudo().tracking_token:
                rec.sudo().tracking_token = secrets.token_urlsafe(24)
            # ترتيب مقصود: إبلاغ الإنشاء أولاً ثم الإسناد - فيصل التاجر
            # حدثان مرتَّبان (أُنشئ، ثم أُسند) بدل إبلاغين متطابقين.
            rec._queue_merchant_webhook()
            rec.auto_assign_nearest_driver()
            rec._notify_dashboard()
        return records

    def write(self, vals):
        new_state = vals.get('state')
        if new_state:
            self._check_transition(new_state)
        # المندوبون السابقون يُلتقطون قبل الكتابة (بعدها فقدنا من كانوا)
        # لكنهم يُحرَّرون *بعدها*: التحرير يسأل "هل عليه طلب حيّ؟"،
        # وقبل الكتابة يكون هذا الطلب نفسه ما زال له - فيبقى "في مهمة"
        # رغم سحب الطلب منه.
        previous_drivers = (self.driver_id if 'driver_id' in vals
                            else self.env['quick.delivery.driver'])

        res = super().write(vals)

        if 'driver_id' in vals:
            # العمولة تُثبَّت لحظة الإسناد، وتُصفَّر إن سُحب المندوب.
            for rec in self:
                rec.sudo().driver_commission = (
                    rec.driver_id.sudo().commission_per_order
                    if rec.driver_id else 0.0)
        if previous_drivers:
            (previous_drivers - self.driver_id).sudo()._qd_refresh_status()
        if new_state and new_state not in self.OPEN_STATES:
            self._release_driver()
        if 'state' in vals or 'driver_id' in vals:
            self._queue_merchant_webhook()
            self._notify_dashboard()
        # الرمز يُرسل عند الإسناد لا عند الإنشاء: قبله لا مندوب يُذكر
        # اسمه، وطلبٌ بلا مندوب ليس عند العميل منه خبر بعد.
        if new_state == 'driver_assigned' or (
                'driver_id' in vals and vals.get('driver_id')):
            assigned = self.filtered(
                lambda rec: rec.state == 'driver_assigned')
            assigned._queue_customer_sms()
            # ختم الإسناد قبل الإشعار: الرقم الذي نقيس به زمن الوصول
            # يجب أن يسبق الدفع لا أن يتبعه.
            assigned._stamp_assignment()
            assigned._queue_driver_push()
        return res

    @api.depends('assigned_at', 'driver_seen_at')
    def _compute_notify_seconds(self):
        for rec in self:
            if rec.assigned_at and rec.driver_seen_at:
                delta = rec.driver_seen_at - rec.assigned_at
                rec.notify_seconds = max(0, int(delta.total_seconds()))
            else:
                rec.notify_seconds = 0

    def _mark_seen_by_driver(self):
        """أول ظهور للطلب على جوال المندوب - يُكتب مرة واحدة.

        الكتابة من المسار العام تحتاج sudo، والشرط يمنع إعادة ضبط
        الرقم مع كل نداء استطلاع كل ثماني ثوان.
        """
        fresh = self.sudo().filtered(
            lambda rec: rec.assigned_at and not rec.driver_seen_at)
        if fresh:
            fresh.write({'driver_seen_at': fields.Datetime.now()})

    @api.model
    def _day_start_utc_for_env(self):
        """بداية اليوم المحلي - يستعملها الداش بورد لحساب أرقام "اليوم"."""
        return _day_start_utc(self.env)

    @api.model
    def _generate_otp(self):
        """secrets لا random: random مُولِّد شبه عشوائي قابل للتوقع إن
        عُرفت بعض مخرجاته. وستة أرقام لا أربعة."""
        return '%06d' % secrets.randbelow(1000000)

    def _check_transition(self, new_state):
        for rec in self:
            if rec.state == new_state:
                continue
            allowed = self.ALLOWED_TRANSITIONS.get(rec.state, ())
            if new_state not in allowed:
                raise UserError(_(
                    'انتقال غير مسموح في الطلب %(order)s: من "%(current)s" '
                    'إلى "%(new)s".'
                ) % {
                    'order': rec.name,
                    'current': dict(rec._fields['state'].selection).get(
                        rec.state, rec.state),
                    'new': dict(rec._fields['state'].selection).get(
                        new_state, new_state),
                })

    # ------------------------------------------------------------------
    # دورة حياة المندوب
    # ------------------------------------------------------------------
    def _release_driver(self):
        """يُعاد المندوب إلى "متاح" حين يُغلق الطلب أو يُلغى.

        النسخة السابقة كانت تعيده فقط من مسارَي التطبيق (تسليم/تعذر) -
        فإلغاء التاجر أو إلغاء غرفة العمليات يُبقي المندوب "في مهمة"
        للأبد، فلا يُسنَد له شيء ولا يظهر متاحاً لأحد.
        """
        self.driver_id.sudo()._qd_refresh_status()

    def _notify_dashboard(self):
        self.env['bus.bus']._sendone('quick_delivery_channel', 'order_updated',
                                     {'refresh': True})

    # ------------------------------------------------------------------
    # الإسناد التلقائي
    # ------------------------------------------------------------------
    @api.model
    def _dispatch_radius_km(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'quick_delivery.dispatch_radius_km')
        try:
            return float(value) if value else DEFAULT_DISPATCH_RADIUS_KM
        except (TypeError, ValueError):
            _logger.warning('قيمة غير صالحة لنطاق الإسناد: %r', value)
            return DEFAULT_DISPATCH_RADIUS_KM

    @api.model
    def cron_retry_auto_assign(self):
        unassigned = self.search([('state', '=', 'searching_driver')],
                                 order='sla_deadline asc', limit=200)
        for order in unassigned:
            order.auto_assign_nearest_driver()

    def auto_assign_nearest_driver(self, max_radius_km=None):
        radius = max_radius_km or self._dispatch_radius_km()
        for rec in self:
            if rec.state != 'searching_driver':
                continue
            # طلب أُنشئ بمندوب محدَّد مسبقاً (استيراد، أو إسناد يدوي مع
            # الإنشاء) لا يُنتزع منه: الإسناد التلقائي كان يستبدله بأقرب
            # متاح، فيصير الإسناد اليدوي بلا أثر.
            if rec.driver_id:
                continue
            # المؤرشف مستبعد تلقائياً من search: مندوبٌ أُوقف لا
            # يُسنَد له شيء دون أن نكتب شرطاً لذلك.
            Driver = self.env['quick.delivery.driver'].sudo()
            # المخصَّص لشركة أخرى يُستبعد هنا لا بعد الترتيب: وإلا رُشّح
            # أقربُ مندوب ثم رُفض، فظهر الطلب بلا مندوب وأقربُهم واقف.
            candidates = Driver.search([
                ('driver_status', '=', 'online'),
                ('current_lat', '!=', 0.0),
                ('current_lng', '!=', 0.0),
                '|', ('client_ids', '=', False),
                ('client_ids', 'in', rec.client_id.id),
            ])
            if not candidates:
                rec._qd_explain_no_driver(Driver, radius)
                continue
            ranked = sorted(
                ((self._haversine(rec.store_lat, rec.store_lng,
                                  drv.current_lat, drv.current_lng), drv)
                 for drv in candidates),
                key=lambda pair: pair[0],
            )
            assigned = False
            for distance, driver in ranked:
                if distance > radius:
                    # أبعد من النطاق: والبقية أبعد (القائمة مرتّبة).
                    break
                # قفل صفّ المندوب قبل إسناده: نداءان متزامنان من الـAPI
                # (طلبان في نفس اللحظة) كانا يرشّحان نفس أقرب مندوب
                # ويسندانه لكليهما - كلٌّ في معاملته لا يرى الأخرى.
                if not driver._qd_lock_if_free():
                    continue
                rec.write({'driver_id': driver.id,
                           'state': 'driver_assigned',
                           'dispatch_note': False})
                driver.sudo().write({'driver_status': 'busy'})
                assigned = True
                break
            if not assigned:
                # لا for/else هنا: الـbreak عند تجاوز النطاق كان
                # يتخطّاه، فلا يُكتب أكثر الأسباب وقوعاً.
                rec._qd_explain_no_driver(Driver, radius, ranked)

    def _qd_explain_no_driver(self, Driver, radius, ranked=None):
        """يكتب على الطلب لماذا لم يجد مندوباً.

        السؤال "لماذا لم يُسنَد" يجب أن يجيبه النظام لا أن يبحث عنه
        المستخدم، ولكلّ سبب قرارٌ مختلف.
        """
        self.ensure_one()
        # مندوبون متاحون لكنهم مخصَّصون لشركات أخرى: سببٌ مختلف
        # تماماً، وقراره مختلف (ارفع التخصيص أو عيّن مندوباً للشركة).
        dedicated_elsewhere = Driver.search_count([
            ('driver_status', '=', 'online'),
            ('client_ids', '!=', False),
            ('client_ids', 'not in', self.client_id.id),
        ])
        if not ranked and dedicated_elsewhere:
            note = _('المندوبون المتاحون مخصَّصون لشركات أخرى - خصّص '
                     'مندوباً لـ%s أو ارفع التخصيص.') % self.client_id.name
            if self.dispatch_note != note:
                self.sudo().dispatch_note = note
            return
        if ranked:
            nearest = ranked[0][0]
            note = _('أقرب مندوب متاح يبعد %(km).1f كم - والنطاق '
                     '%(radius).1f كم. وسّع النطاق أو قرّب مندوباً.') % {
                'km': nearest, 'radius': radius}
        elif Driver.search_count([('driver_status', '=', 'busy')]):
            note = _('كل المندوبين المتاحين على طلبات أخرى - تحتاج '
                     'مندوباً إضافياً.')
        elif Driver.search_count([('driver_status', '=', 'online')]):
            note = _('مندوبون متاحون لكن مواقعهم غير معروفة - لم يفتحوا '
                     'التطبيق أو لم يسمحوا بالموقع.')
        else:
            note = _('لا مندوب متاح الآن - الجميع غير متصل.')
        if self.dispatch_note != note:
            self.sudo().dispatch_note = note

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    # ------------------------------------------------------------------
    # إثبات التسليم
    # ------------------------------------------------------------------
    def verify_otp(self, otp_code):
        """المقارنة في الخادم بـsudo: الحقل محصور بالمدير، والمندوب
        يُدخل الرمز ولا يقرأه."""
        self.ensure_one()
        expected = (self.sudo().delivery_otp or '').strip()
        return bool(expected) and secrets.compare_digest(
            str(otp_code or '').strip(), expected)

    @api.model
    def normalize_photo_payload(self, photo_base64):
        """يقبل data-URI أو base64 خاماً، ويرفض ما ليس صورة.

        النسخة السابقة كانت تقبل أي نص base64 - فيُغلق الطلب "تم التسليم"
        بصورة سوداء أو ببكسل واحد، وهي الطريقة الوحيدة للإغلاق بلا رمز.
        """
        raw = (photo_base64 or '').strip()
        if not raw:
            return False
        if raw.startswith('data:'):
            raw = raw.split(',', 1)[-1]
        try:
            decoded = base64.b64decode(raw, validate=True)
        except Exception:
            raise UserError(_('صورة إثبات التسليم غير صالحة (ترميز base64).'))
        if len(decoded) < 4096:
            raise UserError(_(
                'صورة إثبات التسليم صغيرة جداً (%d بايت) - يُرجى تصوير '
                'الطلب عند الباب.') % len(decoded))
        # JPEG: FF D8 FF | PNG: 89 50 4E 47 | WEBP: RIFF....WEBP
        if not (decoded.startswith(b'\xff\xd8\xff')
                or decoded.startswith(b'\x89PNG')
                or (decoded[:4] == b'RIFF' and decoded[8:12] == b'WEBP')):
            raise UserError(_('ملف إثبات التسليم ليس صورة (JPEG/PNG/WEBP).'))
        return raw

    def action_mark_delivered(self, otp_code=None, photo_base64=None):
        """النقطة الوحيدة لإغلاق الطلب تسليماً - من التطبيق أو من أودو."""
        self.ensure_one()
        vals = {'state': 'delivered', 'delivered_at': fields.Datetime.now()}
        if otp_code:
            if self.otp_attempts >= MAX_OTP_ATTEMPTS:
                raise UserError(_(
                    'تجاوزت حدّ محاولات الرمز (%d) على هذا الطلب. '
                    'أغلقه بصورة إثبات التسليم، أو راجع غرفة العمليات.'
                ) % MAX_OTP_ATTEMPTS)
            if not self.verify_otp(otp_code):
                # المحاولات تُعدّ وتُسجَّل: الحدّ وحده بلا أثر لا يكشف
                # من يحاول التخمين.
                self.sudo().otp_attempts += 1
                _logger.warning(
                    'رمز خاطئ على الطلب %s (المحاولة %d) من المندوب %s',
                    self.name, self.otp_attempts,
                    self.driver_id.name or '-')
                raise UserError(_(
                    'رمز التحقق غير صحيح. المحاولات المتبقية: %d.'
                ) % max(0, MAX_OTP_ATTEMPTS - self.otp_attempts))
            vals['pod_method'] = 'otp'
            vals['otp_attempts'] = 0
        else:
            photo = self.normalize_photo_payload(photo_base64)
            if not photo:
                raise UserError(_(
                    'يُرجى إدخال رمز التحقق من العميل أو تصوير الطلب عند '
                    'الباب - لا يُغلق الطلب بلا إثبات.'))
            vals['pod_photo'] = photo
            vals['pod_method'] = 'photo'
        self.write(vals)
        return True

    def action_mark_failed(self, failure_reason=None, failure_notes=None):
        self.ensure_one()
        valid = dict(self._fields['failure_reason'].selection)
        if failure_reason not in valid:
            raise UserError(_('سبب تعذر التسليم غير معروف: %s')
                            % failure_reason)
        self.write({'state': 'failed',
                    'failure_reason': failure_reason,
                    'failure_notes': failure_notes or ''})
        return True

    # ------------------------------------------------------------------
    # إبلاغ التاجر
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # صفحة تتبع العميل
    # ------------------------------------------------------------------
    STATE_STEPS = ('searching_driver', 'driver_assigned', 'arrived_at_store',
                   'picked_up', 'delivered')

    def _public_tracking_data(self):
        """ما يراه العميل النهائي - ولا شيء غيره.

        لا اسمه ولا عنوانه ولا جواله: يعرفها أصلاً، وإظهارها تُسرَّب
        لمن يقع الرابط بيده. ولا رقم طلب التاجر ولا رسومنا.
        """
        self.ensure_one()
        remaining = 0
        if self.sla_deadline and self.state in self.OPEN_STATES:
            remaining = max(0, int((self.sla_deadline
                                    - fields.Datetime.now()).total_seconds()))
        step = (self.STATE_STEPS.index(self.state)
                if self.state in self.STATE_STEPS else -1)
        return {
            'tracking_number': self.name,
            'state': self.state,
            'state_label': dict(self._fields['state'].selection).get(
                self.state, self.state),
            'step': step,
            'steps_total': len(self.STATE_STEPS),
            'is_open': self.state in self.OPEN_STATES,
            'is_delivered': self.state == 'delivered',
            'remaining_seconds': remaining,
            'store_name': self.store_name,
            'merchant_name': self.client_id.name,
            'bags_count': self.bags_count,
            'cod_amount': self.cod_amount if self.payment_method == 'COD'
                          else 0.0,
            'driver_name': self.driver_id.name or '',
            'driver_phone': self.driver_id.phone or '',
            # الرمز يُعرض ما دام الطلب حياً. بعد التسليم لا معنى له،
            # وإبقاؤه يجعل الرابط المحفوظ في جوال العميل سرّاً بلا سبب.
            'delivery_otp': (self.sudo().delivery_otp
                             if self.state in self.OPEN_STATES else ''),
            'failure_reason': dict(
                self._fields['failure_reason'].selection).get(
                    self.failure_reason, '') if self.failure_reason else '',
        }

    # ------------------------------------------------------------------
    # رسالة العميل
    # ------------------------------------------------------------------
    def _qd_sms_body(self, template):
        """نص الرسالة من قالب المزوّد."""
        self.ensure_one()
        return (template or '')\
            .replace('{otp}', self.sudo().delivery_otp or '')\
            .replace('{driver}', self.driver_id.name or '')\
            .replace('{merchant}', self.client_id.name or '')\
            .replace('{order}', self.name or '')\
            .replace('{tracking_url}', self.tracking_url or '')\
            .replace('{cod_amount}', '%.2f' % (self.cod_amount or 0.0))

    def _queue_customer_sms(self):
        """يُسجَّل في صندوق صادر ويُرسل بعد تثبيت المعاملة.

        الرمز كان يُسلَّم للتاجر ليُوصله، والسلسلة تنقطع عند أول تاجر
        لا يفعل - فيقف المندوب عند الباب بلا سبيل للإغلاق. هنا نُرسله
        نحن.
        """
        channel = self.env['quick.delivery.channel'].sudo().search(
            [], order='sequence, id', limit=1)
        if not channel:
            return
        Message = self.env['quick.delivery.message'].sudo()
        for rec in self:
            if not rec.client_id.sudo().qd_sms_customer:
                continue
            if not rec.customer_phone or not rec.driver_id:
                continue
            # قيد التفرّد يحمي من التكرار، لكن الفحص هنا يتجنّب
            # استثناءً في كل إعادة إسناد.
            if Message.search_count([('order_id', '=', rec.id),
                                     ('kind', '=', 'otp')]):
                continue
            Message.create({
                'order_id': rec.id,
                'phone': rec.customer_phone,
                'body': rec._qd_sms_body(channel.message_template),
                'kind': 'otp',
            })

    def _stamp_assignment(self):
        for rec in self:
            rec.sudo().write({'assigned_at': fields.Datetime.now(),
                              'driver_seen_at': False})

    def _queue_driver_push(self):
        """إشعار المندوب والتطبيق مغلق.

        بلا تفاصيل عمداً - نفس قاعدة إشعار التطبيق: لا اسم عميل ولا
        عنوان ولا مبلغ على شاشة مقفلة في جهاز قد يُسلَّم لمندوب آخر
        غداً. الفرع وحده يكفي ليعرف إلى أين يتحرّك.
        """
        Push = self.env['quick.delivery.push'].sudo()
        for rec in self:
            if not rec.driver_id:
                continue
            if Push.search_count([('order_id', '=', rec.id),
                                  ('driver_id', '=', rec.driver_id.id),
                                  ('kind', '=', 'new_order')]):
                continue
            Push._enqueue(
                rec.driver_id,
                title=_('طلب توصيل جديد'),
                body=_('%(store)s - افتح التطبيق للتفاصيل') % {
                    'store': rec.store_name or rec.client_id.name or ''},
                url='/driver',
                order=rec,
            )

    def _merchant_webhook_payload(self):
        self.ensure_one()
        return {
            'tracking_number': self.name,
            'order_id': self.merchant_order_id,
            'status': self.state,
            # رمز الـOTP *لا* يُرسل هنا: يُسلَّم مرة واحدة في رد إنشاء
            # الطلب ليعرضه التاجر لعميله. إعادة إرساله في كل تغيير حالة
            # تنشره بلا داعٍ في سجلات التاجر وشبكته.
            # الرابط يُرسل في كل إبلاغ ليضعه التاجر في رسالته لعميله.
            # الرمز نفسه لا يُرسل: من فتح الرابط رآه، ومن لم يفتحه لا
            # داعي لنشره في سجلات التاجر وشبكته.
            'tracking_url': self.tracking_url or None,
            'failure_reason': self.failure_reason or None,
            'failure_notes': self.failure_notes or None,
            'pod_method': self.pod_method or None,
            'driver': {
                'name': self.driver_id.name or None,
                'phone': self.driver_id.phone or None,
                'lat': self.driver_id.current_lat or None,
                'lng': self.driver_id.current_lng or None,
            } if self.driver_id else None,
            'timestamp': fields.Datetime.now().isoformat(),
        }

    def _queue_merchant_webhook(self):
        """يُسجَّل في صندوق صادر داخل نفس المعاملة، ويُرسل بعد تثبيتها.

        النسخة السابقة كانت تنفّذ requests.post داخل write() - أي قبل
        تثبيت المعاملة: لو ارتدّت بعدها، يكون التاجر أُبلغ بتسليم لم
        يحدث. وكان الفشل يُهمل بصمت (except: pass) بلا سجل ولا إعادة
        محاولة، فانقطاع ثلاث دقائق في سيرفر التاجر = طلبات لا يعرف بها
        أبداً.
        """
        Outbox = self.env['quick.delivery.webhook'].sudo()
        for rec in self:
            if not rec.client_id.sudo().webhook_url:
                continue
            Outbox.create({
                'order_id': rec.id,
                'payload': rec._merchant_webhook_payload(),
            })
