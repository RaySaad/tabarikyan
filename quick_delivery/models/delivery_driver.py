# -*- coding: utf-8 -*-
"""المندوب ككيان منفصل - لا مستخدم أودو داخلي.

الفرق ليس تنظيمياً:

* **الرخصة**: Odoo.sh يحاسب على كل مستخدم داخلي. عشرون مندوباً كانوا
  عشرين رخصة لمن يحتاج شاشة واحدة.
* **الأمن**: المستخدم الداخلي يدخل /web ويرى ما تسمح به مجموعته - وجوال
  المندوب يُسلَّم لغيره غداً. الكيان المنفصل لا يملك دخولاً لأودو
  إطلاقاً: رمز جلسة ينتهي، ومسارات API محدودة.
* **الدخول**: رمز بـ43 حرفاً لا يُكتب على جوال. هنا: جوال + رمز سري
  (PIN) مُعمّى، والخادم يُصدر رمز جلسة.
"""
import logging
import re
import secrets
from datetime import timedelta

from passlib.context import CryptContext

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# الـPIN سرٌّ منخفض الإنتروبيا (أربعة إلى ستة أرقام)، فيُعمّى بعدد
# دورات كامل - لا بالعدد المخفّض الذي تستعمله أودو لمفاتيح الـAPI
# العشوائية. والقفل بعد المحاولات الخاطئة هو الحماية الحقيقية.
PIN_CRYPT_CONTEXT = CryptContext(['pbkdf2_sha512'])

PIN_RE = re.compile(r'^\d{4,6}$')

# عمر جلسة التطبيق: وردية كاملة وزيادة، ثم إعادة دخول.
SESSION_HOURS = 16
MAX_PIN_ATTEMPTS = 5
LOCK_MINUTES = 15


class QuickDeliveryDriver(models.Model):
    _name = 'quick.delivery.driver'
    _description = 'مندوب توصيل فوري'
    _order = 'name'

    name = fields.Char(string='اسم المندوب', required=True, index=True)
    active = fields.Boolean(string='نشط', default=True)
    phone = fields.Char(
        string='جوال المندوب', required=True,
        help='رقم الدخول إلى التطبيق. يُقبل بأي صيغة (05x أو +9665x أو '
             '009665x) - المقارنة على آخر تسع خانات.')
    # مفتاح الدخول: آخر تسع خانات من الأرقام وحدها. المندوب يكتب رقمه
    # كما يحفظه - 0551234567 أو +966551234567 - فلا يُحرم من الدخول
    # لاختلاف صيغة لا معنى له.
    login_key = fields.Char(
        string='مفتاح الدخول', compute='_compute_login_key',
        store=True, index=True, copy=False)
    vehicle_plate = fields.Char(string='لوحة المركبة')
    notes = fields.Text(string='ملاحظات')

    # ------------------------------------------------------------------
    # بيانات الدخول
    # ------------------------------------------------------------------
    pin = fields.Char(
        string='رمز الدخول (PIN)', compute='_compute_pin',
        inverse='_inverse_pin', groups='quick_delivery.group_qd_manager',
        help='أربعة إلى ستة أرقام. يُخزَّن مُعمّى - فلا يُقرأ بعد كتابته '
             'ولا من قاعدة البيانات. إن نسيه المندوب يُولَّد غيره.')
    pin_hash = fields.Char(
        string='بصمة رمز الدخول', copy=False,
        groups='quick_delivery.group_qd_manager')
    has_pin = fields.Boolean(
        string='له رمز دخول', compute='_compute_has_pin',
        search='_search_has_pin', compute_sudo=True,
        help='مندوب بلا رمز لا يستطيع الدخول إلى التطبيق.')
    session_token = fields.Char(
        string='رمز الجلسة', copy=False, index=True,
        groups='quick_delivery.group_qd_manager')
    session_expiry = fields.Datetime(
        string='انتهاء الجلسة', copy=False,
        groups='quick_delivery.group_qd_manager')
    session_device = fields.Char(
        string='الجهاز', copy=False, readonly=True,
        groups='quick_delivery.group_qd_manager')
    login_fail_count = fields.Integer(
        string='محاولات دخول فاشلة', copy=False, readonly=True)
    login_locked_until = fields.Datetime(
        string='مقفول حتى', copy=False, readonly=True)

    # ------------------------------------------------------------------
    # الحالة والموقع
    # ------------------------------------------------------------------
    driver_status = fields.Selection([
        ('offline', 'غير متصل'),
        ('online', 'متاح للطلبات'),
        ('busy', 'في مهمة توصيل'),
    ], default='offline', string='حالة المندوب', required=True, index=True)
    current_lat = fields.Float(string='خط العرض الحالي', digits=(10, 7))
    current_lng = fields.Float(string='خط الطول الحالي', digits=(10, 7))
    last_ping = fields.Datetime(string='آخر تحديث موقع')

    # ------------------------------------------------------------------
    # المحفظة والعهدة
    # ------------------------------------------------------------------
    commission_per_order = fields.Float(
        string='عمولة المندوب للطلب (SAR)', default=8.0,
        groups='quick_delivery.group_qd_manager')
    cod_custody_balance = fields.Float(
        string='عهدة التحصيل النقدي (COD)', compute='_compute_driver_wallet',
        compute_sudo=True)
    today_delivered_count = fields.Integer(
        string='طلبات اليوم المنجزة', compute='_compute_driver_wallet',
        compute_sudo=True)
    today_earnings = fields.Float(
        string='أرباح اليوم (SAR)', compute='_compute_driver_wallet',
        compute_sudo=True)

    order_ids = fields.One2many('quick.delivery.order', 'driver_id',
                                string='الطلبات')

    _login_key_uniq = models.Constraint(
        'unique(login_key)',
        'رقم الجوال هذا مسجَّل لمندوب آخر - رقم الدخول يجب أن يكون فريداً.',
    )
    _session_token_uniq = models.Constraint(
        'unique(session_token)',
        'رمز الجلسة مستخدم لمندوب آخر بالفعل.',
    )

    # ------------------------------------------------------------------
    # الحقول المحسوبة والقيود
    # ------------------------------------------------------------------
    @api.model
    def _phone_key(self, phone):
        digits = re.sub(r'\D', '', phone or '')
        return digits[-9:] if len(digits) >= 9 else digits

    @api.depends('phone')
    def _compute_login_key(self):
        for rec in self:
            rec.login_key = self._phone_key(rec.phone)

    @api.constrains('phone')
    def _check_phone(self):
        for rec in self:
            if len(self._phone_key(rec.phone)) < 9:
                raise ValidationError(_(
                    'جوال المندوب "%s" قصير - يجب أن يحمل تسع خانات على '
                    'الأقل ليكون رقم دخول صالحاً.') % (rec.phone or ''))

    def _compute_pin(self):
        """لا يُقرأ أبداً: المخزَّن بصمةٌ لا نصّ."""
        for rec in self:
            rec.pin = ''

    def _inverse_pin(self):
        for rec in self:
            value = (rec.pin or '').strip()
            if not value:
                continue
            if not PIN_RE.match(value):
                raise ValidationError(_(
                    'رمز الدخول يجب أن يكون من أربعة إلى ستة أرقام فقط.'))
            rec.sudo().write({
                'pin_hash': PIN_CRYPT_CONTEXT.hash(value),
                # رمز جديد يُنهي الجلسات القائمة: من يُغيَّر رمزه يُخرج
                # من كل جهاز، وإلا بقي الجهاز المفقود داخلاً.
                'session_token': False,
                'session_expiry': False,
                'login_fail_count': 0,
                'login_locked_until': False,
            })

    @api.depends('pin_hash')
    def _compute_has_pin(self):
        for rec in self:
            rec.has_pin = bool(rec.sudo().pin_hash)

    def _search_has_pin(self, operator, value):
        """حقل محسوب غير مخزَّن لا يُبحث فيه بلا هذه الدالة - وغرفة
        العمليات تحتاج "من لم يُسلَّم رمزه بعد" قبل بداية الوردية."""
        if operator not in ('in', 'not in'):
            raise NotImplementedError(operator)
        wanted = True in value
        if operator == 'not in':
            wanted = not wanted
        return [('pin_hash', '!=', False)] if wanted             else [('pin_hash', '=', False)]

    def _compute_driver_wallet(self):
        """استعلامان مُجمَّعان للمجموعة كلها، لا استعلاماك لكل مندوب.

        الداش بورد يقرأ هذه الحقول لكل مندوب في كل تحديث.
        """
        Order = self.env['quick.delivery.order'].sudo()
        day_start = Order._day_start_utc_for_env()

        cod_groups = Order._read_group(
            [('driver_id', 'in', self.ids), ('state', '=', 'delivered'),
             ('payment_method', '=', 'COD'), ('is_cod_settled', '=', False)],
            groupby=['driver_id'], aggregates=['cod_amount:sum'])
        cod_by_driver = {driver.id: total for driver, total in cod_groups}

        today_groups = Order._read_group(
            [('driver_id', 'in', self.ids), ('state', '=', 'delivered'),
             ('delivered_at', '>=', day_start)],
            groupby=['driver_id'], aggregates=['__count'])
        count_by_driver = {driver.id: count for driver, count in today_groups}

        for rec in self:
            rec.cod_custody_balance = cod_by_driver.get(rec.id, 0.0)
            delivered_today = count_by_driver.get(rec.id, 0)
            rec.today_delivered_count = delivered_today
            rec.today_earnings = (delivered_today
                                  * rec.sudo().commission_per_order)

    # ------------------------------------------------------------------
    # الدخول والجلسة
    # ------------------------------------------------------------------
    @api.model
    def _qd_login_lock_minutes(self, phone):
        """كم دقيقة باقية على قفل هذا الرقم؟ صفر إن لم يكن مقفولاً."""
        driver = self.sudo().search(
            [('login_key', '=', self._phone_key(phone))], limit=1)
        if not driver or not driver.login_locked_until:
            return 0
        seconds = (driver.login_locked_until
                   - fields.Datetime.now()).total_seconds()
        return int(seconds // 60) + 1 if seconds > 0 else 0

    @api.model
    def _qd_authenticate(self, phone, pin):
        """المندوب إن صحّ الجوال والرمز، أو مجموعة فارغة.

        رسالة واحدة لجوال خاطئ ولرمز خاطئ: التمييز بينهما يُفشي من هو
        مندوب ومن ليس. والفشل يُحتسب ويُقفل - ستة أرقام تُخمَّن في
        دقائق بلا قفل.
        """
        pin = (pin or '').strip()
        driver = self.sudo().search(
            [('login_key', '=', self._phone_key(phone))], limit=1)
        if not driver or not pin:
            return self.browse()
        if driver.login_locked_until \
                and driver.login_locked_until > fields.Datetime.now():
            return self.browse()
        stored = driver.pin_hash
        if not stored or not PIN_CRYPT_CONTEXT.verify(pin, stored):
            driver._qd_register_failed_login()
            return self.browse()
        return driver

    def _qd_register_failed_login(self):
        self.ensure_one()
        count = self.login_fail_count + 1
        vals = {'login_fail_count': count}
        if count >= MAX_PIN_ATTEMPTS:
            vals.update({
                'login_locked_until': (fields.Datetime.now()
                                       + timedelta(minutes=LOCK_MINUTES)),
                'login_fail_count': 0,
            })
            _logger.warning(
                'قفل دخول تطبيق المندوب %s (id=%s) بعد %d محاولة خاطئة',
                self.name, self.id, MAX_PIN_ATTEMPTS)
        self.sudo().write(vals)

    def _qd_open_session(self, device=None):
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.sudo().write({
            'session_token': token,
            'session_expiry': (fields.Datetime.now()
                               + timedelta(hours=SESSION_HOURS)),
            'session_device': (device or '')[:120],
            'login_fail_count': 0,
            'login_locked_until': False,
        })
        _logger.info('دخول تطبيق المندوب %s (id=%s)', self.name, self.id)
        return token

    def _qd_close_session(self):
        self.sudo().write({'session_token': False, 'session_expiry': False})

    @api.model
    def _qd_driver_from_session(self, token):
        """المندوب من رمز الجلسة - مع رفض الفارغ والمنتهي.

        search الافتراضي يستبعد المؤرشف: مندوبٌ أُوقف تنتهي جلسته فوراً.
        """
        token = (token or '').strip()
        if not token:
            return self.browse()
        driver = self.sudo().search([('session_token', '=', token)], limit=1)
        if not driver:
            return self.browse()
        if not driver.session_expiry \
                or driver.session_expiry <= fields.Datetime.now():
            return self.browse()
        return driver

    # ------------------------------------------------------------------
    # دورة حياة المندوب
    # ------------------------------------------------------------------
    def _qd_has_open_order(self):
        """هل على المندوب طلب حيّ الآن؟"""
        self.ensure_one()
        Order = self.env['quick.delivery.order'].sudo()
        return bool(Order.search_count([
            ('driver_id', '=', self.id),
            ('state', 'in', Order.OPEN_STATES),
        ]))

    def _qd_refresh_status(self):
        """يُعيد حالة المندوب إلى واقعها بعد إغلاق طلب أو سحبه منه.

        لا نكتب 'online' على عمياء: المندوب قد يكون أنهى وردية فصار
        offline، وقد يكون عليه طلب آخر فيبقى busy.
        """
        for rec in self:
            if rec.driver_status == 'offline':
                continue
            target = 'busy' if rec._qd_has_open_order() else 'online'
            if rec.driver_status != target:
                rec.sudo().write({'driver_status': target})

    def _qd_lock_if_free(self):
        """يقفل صفّ المندوب ويؤكد أنه ما زال متاحاً وبلا طلب حيّ.

        بلا هذا القفل، نداءان متزامنان من الـAPI يرشّحان نفس أقرب مندوب
        ويسندانه لكليهما: كلٌّ في معاملته لا يرى كتابة الأخرى حتى
        تُثبَّت. NOWAIT لا SKIP LOCKED: إن كان مقفولاً من معاملة أخرى
        فهي على وشك إسناده، فننتقل للذي بعده بدل الانتظار.
        """
        self.ensure_one()
        # نقطة حفظ إلزامية: خطأ قفل في بوستجرس يُفسد المعاملة كلها، فلا
        # يكفي التقاط الاستثناء في بايثون - لا بد من التراجع إلى نقطة.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    'SELECT id FROM quick_delivery_driver '
                    'WHERE id = %s FOR UPDATE NOWAIT', (self.id,))
        except Exception:
            # قفل فاشل = مندوب تحت الإسناد في معاملة أخرى.
            return False
        self.invalidate_recordset(['driver_status'])
        if self.sudo().driver_status != 'online':
            return False
        return not self._qd_has_open_order()

    # ------------------------------------------------------------------
    # أزرار الواجهة
    # ------------------------------------------------------------------
    def action_generate_pin(self):
        """رمز عشوائي يُعرض مرة واحدة - المخزَّن بصمته لا نصّه."""
        self.ensure_one()
        new_pin = '%06d' % secrets.randbelow(1000000)
        self.pin = new_pin
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('رمز دخول المندوب %s') % self.name,
                'message': _(
                    'الرمز: %(pin)s — الجوال للدخول: %(phone)s. اكتبه الآن '
                    'وأعطه للمندوب: لن يُعرض مرة أخرى، والمخزَّن بصمته لا '
                    'نصّه. وجلساته القائمة أُنهيت.'
                ) % {'pin': new_pin, 'phone': self.phone or ''},
                'sticky': True,
                'type': 'warning',
            },
        }

    def action_revoke_sessions(self):
        """إخراج المندوب من كل جهاز - لجوال مفقود أو مندوب أُوقف."""
        self._qd_close_session()
        return True

    def action_settle_driver_cod(self):
        Order = self.env['quick.delivery.order'].sudo()
        for rec in self:
            unsettled = Order.search([
                ('driver_id', '=', rec.id),
                ('state', '=', 'delivered'),
                ('payment_method', '=', 'COD'),
                ('is_cod_settled', '=', False),
            ])
            if not unsettled:
                raise UserError(_('لا توجد عهدة تحصيل غير مسوّاة على %s.')
                                % rec.name)
            settled_total = sum(unsettled.mapped('cod_amount'))
            unsettled.write({'is_cod_settled': True,
                             'cod_settled_at': fields.Datetime.now()})
            # أثرٌ مكتوب للتسوية: رقم نقدي يُسوّى بلا سجل لا يمكن مراجعته.
            _logger.info('تسوية عهدة COD للمندوب %s (id=%s): %.2f على %d طلب',
                         rec.name, rec.id, settled_total, len(unsettled))
