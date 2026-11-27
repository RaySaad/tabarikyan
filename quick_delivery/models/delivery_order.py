# -*- coding: utf-8 -*-
import base64
import logging
import math
import secrets
from datetime import timedelta

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# نطاق البحث الافتراضي عن مندوب (كم). يُقرأ من إعدادات النظام
# (quick_delivery.dispatch_radius_km) ليُعدَّل بلا تعديل كود.
DEFAULT_DISPATCH_RADIUS_KM = 6.0

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
    api_key = fields.Char(
        string='API Key', copy=False, groups='quick_delivery.group_qd_manager')
    webhook_url = fields.Char(
        string='Webhook URL', groups='quick_delivery.group_qd_manager')
    webhook_secret = fields.Char(
        string='Webhook Secret', groups='quick_delivery.group_qd_manager')
    delivery_fee_per_order = fields.Float(
        string='رسوم التوصيل للطلب (SAR)', default=12.0,
        groups='quick_delivery.group_qd_manager')

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
    qd_is_configured = fields.Boolean(
        string='الربط مكتمل', compute='_compute_qd_is_configured',
        search='_search_qd_is_configured', compute_sudo=True,
        help='له مفتاح API ورابط إبلاغ - أي يستطيع إرسال الطلبات '
             'واستقبال تغيّر الحالة.')

    _qd_api_key_uniq = models.Constraint(
        'unique(api_key)',
        'مفتاح الـAPI مستخدم لعميل آخر بالفعل - لكل سوبرماركت مفتاحه.',
    )

    @api.depends('api_key', 'webhook_url')
    def _compute_qd_is_configured(self):
        for rec in self:
            data = rec.sudo()
            rec.qd_is_configured = bool(data.api_key and data.webhook_url)

    def _search_qd_is_configured(self, operator, value):
        """محسوب غير مخزَّن لا يُبحث فيه بلا هذه الدالة - والفلتر
        المطلوب هو "من ربطه ناقص" قبل أن يُرسل أول طلب."""
        if operator not in ('in', 'not in'):
            raise NotImplementedError(operator)
        wanted = True in value
        if operator == 'not in':
            wanted = not wanted
        ready = ['&', ('api_key', '!=', False), ('webhook_url', '!=', False)]
        if wanted:
            return ready
        return ['!'] + ready

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
    delivery_otp = fields.Char(string='رمز التحقق (OTP)', copy=False,
                               groups='quick_delivery.group_qd_manager')
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
    driver_id = fields.Many2one('quick.delivery.driver',
                                string='المندوب المسند', index=True,
                                ondelete='restrict')
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
        return res

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
            candidates = self.env['quick.delivery.driver'].sudo().search([
                ('driver_status', '=', 'online'),
                ('current_lat', '!=', 0.0),
                ('current_lng', '!=', 0.0),
            ])
            ranked = sorted(
                ((self._haversine(rec.store_lat, rec.store_lng,
                                  drv.current_lat, drv.current_lng), drv)
                 for drv in candidates),
                key=lambda pair: pair[0],
            )
            for distance, driver in ranked:
                if distance > radius:
                    break
                # قفل صفّ المندوب قبل إسناده: نداءان متزامنان من الـAPI
                # (طلبان في نفس اللحظة) كانا يرشّحان نفس أقرب مندوب
                # ويسندانه لكليهما - كلٌّ في معاملته لا يرى الأخرى.
                if not driver._qd_lock_if_free():
                    continue
                rec.write({'driver_id': driver.id,
                           'state': 'driver_assigned'})
                driver.sudo().write({'driver_status': 'busy'})
                break

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
            if not self.verify_otp(otp_code):
                raise UserError(_('رمز التحقق (OTP) غير صحيح.'))
            vals['pod_method'] = 'otp'
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
    def _merchant_webhook_payload(self):
        self.ensure_one()
        return {
            'tracking_number': self.name,
            'order_id': self.merchant_order_id,
            'status': self.state,
            # رمز الـOTP *لا* يُرسل هنا: يُسلَّم مرة واحدة في رد إنشاء
            # الطلب ليعرضه التاجر لعميله. إعادة إرساله في كل تغيير حالة
            # تنشره بلا داعٍ في سجلات التاجر وشبكته.
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
