# -*- coding: utf-8 -*-
import functools
import json
import logging

import psycopg2

from odoo import http, fields, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request, Response
from odoo.tools import file_open

from ..models.intake import MAX_BODY_BYTES

_logger = logging.getLogger(__name__)

DISPATCHER_GROUP = 'quick_delivery.group_qd_dispatcher'

# مجلد تطبيق المندوب: صفحة واحدة عامة لا تحمل بياناً، والبيانات تأتي
# بعد الدخول عبر مسارات الـAPI بحاملِ رمز الجلسة.
DRIVER_APP_DIR = 'quick_delivery/static/src/driver_app'


def _json_response(data, status=200):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        content_type='application/json;charset=utf-8',
    )


class BadRequest(Exception):
    """خطأ متوقع في طلب خارجي - يُترجم إلى رد JSON برمز حالة مناسب."""

    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        # رمزٌ يفهمه التطبيق بلا قراءة نص عربي: session_expired يُعيده
        # إلى شاشة الدخول بدل إظهار رسالة خطأ لا حلّ لها.
        self.code = code


def api_endpoint(func):
    """يحوّل كل استثناء إلى رد JSON مفهوم بدل صفحة خطأ 500.

    النسخة السابقة كانت تُرجع تتبّع كود بايثون كاملاً للعثيم/بندة عند
    أي حقل ناقص أو JSON معطوب (لا try حول json.loads، والحقول المطلوبة
    في النموذج تُخرج استثناءً غير ملتقط).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BadRequest as error:
            payload = {'status': 'error', 'error': str(error)}
            if error.code:
                payload['code'] = error.code
            response = _json_response(payload, error.status)
            retry_after = getattr(error, 'retry_after', 0)
            if retry_after:
                response.headers['Retry-After'] = str(retry_after)
            return response
        except (UserError, ValidationError) as error:
            return _json_response(
                {'status': 'error', 'error': error.args[0] if error.args
                 else _('بيانات غير صالحة')}, 400)
        except AccessError:
            return _json_response({'status': 'error',
                                   'error': 'Forbidden'}, 403)
        except psycopg2.DatabaseError:
            # لا نلتقط أخطاء قاعدة البيانات: أودو تبني عليها آليتها.
            # ReadOnlySqlTransaction تحديداً: المسارات بـauth='none'
            # تبدأ بمؤشّر قراءة فقط افتراضياً (http.py:947)، وأودو
            # تُعيد المحاولة بمؤشّر كتابة *عند انتشار* هذا الاستثناء
            # (http.py:2277). التقاطه كان يحوّل محاولة ناجحة إلى 500
            # دائم - وكذلك يُبطل إعادة المحاولة عند تعارض المعاملات
            # (SerializationFailure) ورسالة التكرار المفهومة
            # (IntegrityError).
            raise
        except Exception:
            # السجل يحمل التفصيل، والرد لا يحمله: لا نسرّب بنية النظام
            # لمن يستدعي الـAPI.
            _logger.exception('خطأ غير متوقع في %s', func.__name__)
            return _json_response({'status': 'error',
                                   'error': 'Internal error'}, 500)
    return wrapper


def _throttle(scope, ident):
    """يرفع 429 عند تجاوز الحدّ، مع ترويسة Retry-After.

    الترويسة ليست تجميلاً: أنظمة التجّار تقرأها فتهدأ، وبدونها
    تُعيد المحاولة فوراً فتُضاعف الضغط الذي نحاول تخفيفه.
    """
    allowed, retry_after = request.env[
        'quick.delivery.throttle'].sudo()._qd_hit(scope, ident)
    if not allowed:
        error = BadRequest(
            'تجاوزت حدّ عدد الطلبات. أعد المحاولة بعد %d ثانية.'
            % retry_after, 429)
        error.retry_after = retry_after
        raise error


def _body_json():
    try:
        raw = request.httprequest.get_data(as_text=True)
        data = json.loads(raw or '{}')
    except Exception:
        raise BadRequest('JSON غير صالح في جسم الطلب')
    if not isinstance(data, dict):
        raise BadRequest('جسم الطلب يجب أن يكون كائن JSON')
    return data


def _require(data, *names):
    missing = [name for name in names
               if data.get(name) in (None, '', [], {})]
    if missing:
        raise BadRequest('حقول مطلوبة ناقصة: %s' % ', '.join(missing))


def _coordinate(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BadRequest('قيمة %s ليست رقماً: %r' % (label, value))
    if not number:
        raise BadRequest('قيمة %s مفقودة - لا يمكن الإسناد بلا موقع' % label)
    return number


def _session_driver():
    """المندوب من رمز الجلسة في ترويسة Authorization.

    الرمز هنا جلسة تنتهي بعد وردية، لا رمزاً أبدياً كما كان: جوال
    مفقود يخرج من الخدمة بانتهاء الجلسة أو بزر "إنهاء الجلسات"،
    والمندوب المؤرشف يُرفض فوراً (search يستبعد المؤرشف).
    """
    header = request.httprequest.headers.get('Authorization', '')
    token = header.removeprefix('Bearer ').strip()
    if not token:
        raise BadRequest('الجلسة غير صالحة - يُرجى الدخول من جديد', 401,
                         code='session_expired')
    driver = request.env['quick.delivery.driver'].sudo(
    )._qd_driver_from_session(token)
    if not driver:
        raise BadRequest('انتهت الجلسة - يُرجى الدخول من جديد', 401,
                         code='session_expired')
    return driver


def _order_of_driver(driver, order_id):
    order = request.env['quick.delivery.order'].sudo().browse(int(order_id))
    if not order.exists() or order.driver_id.id != driver.id:
        raise BadRequest('Forbidden', 403)
    return order


def _order_payload(order):
    remaining = 0
    if order.sla_deadline:
        remaining = max(0, int((order.sla_deadline
                                - fields.Datetime.now()).total_seconds()))
    return {
        'id': order.id,
        'tracking_number': order.name,
        'merchant_order_id': order.merchant_order_id,
        'client_name': order.client_id.name,
        'store_name': order.store_name,
        'store_lat': order.store_lat,
        'store_lng': order.store_lng,
        'customer_name': order.customer_name,
        'customer_phone': order.customer_phone,
        'customer_lat': order.customer_lat,
        'customer_lng': order.customer_lng,
        'address_notes': order.address_notes or '',
        'bags_count': order.bags_count,
        'cod_amount': order.cod_amount,
        'payment_method': order.payment_method,
        'state': order.state,
        'remaining_seconds': remaining,
        'accepted': bool(order.accepted_at),
        'accept_seconds_left': order._accept_seconds_left(),
    }


def _wallet_payload(driver):
    return {
        'cod_custody': driver.cod_custody_balance,
        'today_orders': driver.today_delivered_count,
        'today_earnings': driver.today_earnings,
    }


class QuickCommerceController(http.Controller):

    # ==================================================================
    # 1. استقبال الطلب من السوبرماركت (العثيم / بندة)
    # ==================================================================
    @http.route('/api/v1/qcommerce/orders', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def create_qcommerce_order(self, **kwargs):
        api_key = (request.httprequest.headers.get('X-API-Key') or '').strip()
        if not api_key:
            raise BadRequest('Invalid API Key', 401)
        # الحدّ على العنوان قبل التحقّق من المفتاح: وإلا صار تخمين
        # المفاتيح بلا حدّ، وكل محاولة تُنفّذ بصمة.
        _throttle('orders', request.httprequest.remote_addr)
        client = request.env['res.partner'].sudo()._qd_client_from_api_key(
            api_key)
        if not client:
            raise BadRequest('Invalid API Key', 401)
        _throttle('orders', 'client-%s' % client.id)

        data = _body_json()
        store = data.get('store') or {}
        cust = data.get('customer') or {}
        pay = data.get('payment') or {}

        _require(data, 'order_id')
        _require(store, 'store_name')
        _require(cust, 'name', 'phone')

        merchant_order_id = str(data['order_id']).strip()
        Order = request.env['quick.delivery.order'].sudo()
        existing = Order.search([
            ('client_id', '=', client.id),
            ('merchant_order_id', '=', merchant_order_id),
        ], limit=1)
        if existing:
            payload = self._intake_result(existing)
            payload['message'] = 'Order already exists'
            return _json_response(payload, 200)

        method = str(pay.get('method') or 'PREPAID').upper()
        if method not in ('PREPAID', 'COD'):
            raise BadRequest('طريقة دفع غير معروفة: %s' % method)
        try:
            sla_minutes = int(data.get('sla_minutes') or 30)
        except (TypeError, ValueError):
            raise BadRequest('sla_minutes ليست رقماً')

        order = Order.create({
            'client_id': client.id,
            'merchant_order_id': merchant_order_id,
            'sla_minutes': sla_minutes,
            'store_code': store.get('store_code'),
            'store_name': store['store_name'],
            'store_lat': _coordinate(store.get('lat'), 'store.lat'),
            'store_lng': _coordinate(store.get('lng'), 'store.lng'),
            'customer_name': cust['name'],
            'customer_phone': cust['phone'],
            'customer_lat': _coordinate(cust.get('lat'), 'customer.lat'),
            'customer_lng': _coordinate(cust.get('lng'), 'customer.lng'),
            'address_notes': cust.get('address_notes', ''),
            'bags_count': int(data.get('bags_count') or 1),
            'payment_method': method,
            # مبلغ التحصيل للـCOD وحده: مبلغ على طلب مدفوع مسبقاً يعني
            # عهدة وهمية على المندوب.
            'cod_amount': (float(pay.get('cod_amount') or 0.0)
                           if method == 'COD' else 0.0),
        })

        return _json_response(self._intake_result(order), 201)

    # ==================================================================
    # 1-ب. مسار الاستقبال الخاص بكل تاجر
    # ==================================================================
    @http.route('/api/v1/intake/<string:code>', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def merchant_intake(self, code, **kwargs):
        """يستقبل بصيغة التاجر، لا بصيغتنا.

        المواصفة تأتي من العثيم وبندة لا منّا. وهذا المسار يُحفظ فيه
        النداء **كما وصل** قبل أي محاولة فهم: نكتب المُحوّل من نداء
        حقيقي لا من وثيقة، وما التُقط قبل كتابته يُعاد تحويله بزر.

        الرمز في الرابط سرّ بذاته (جزء عشوائي)، فالمسار غير مُخمَّن.
        """
        Inbox = request.env['quick.delivery.inbox'].sudo()
        client = request.env['res.partner'].sudo().search([
            ('qd_intake_code', '=', code),
            ('is_qcommerce_client', '=', True),
        ], limit=1)
        if not client:
            raise BadRequest('Unknown endpoint', 404)
        _throttle('intake', 'client-%s' % client.id)

        length = request.httprequest.content_length or 0
        if length > MAX_BODY_BYTES:
            raise BadRequest(
                'جسم الطلب أكبر من الحدّ (%d بايت)' % MAX_BODY_BYTES, 413)
        raw_body = request.httprequest.get_data(as_text=True)

        if not client.qd_capture_mode:
            # وضع الإنتاج: صارم. قبول طلب لا نفهمه يعني طلباً لن يصل
            # أحداً والتاجر يظنّه مقبولاً.
            try:
                data = json.loads(raw_body or '')
            except Exception:
                raise BadRequest('JSON غير صالح في جسم الطلب')
            if not isinstance(data, dict):
                raise BadRequest('جسم الطلب يجب أن يكون كائن JSON')
            instruction = Inbox._qd_map_payload(client, data)
            order, note, created = Inbox._qd_apply(client, instruction)
            if not order:
                # حدث لا يخصّ الطلبات: مقبولٌ ومفهوم، لا خطأ.
                return _json_response({'status': 'ignored', 'note': note}, 202)
            payload = self._intake_result(order)
            payload['note'] = note
            return _json_response(payload, 201 if created else 200)

        # وضع الالتقاط: يُحفظ أولاً، ثم يُحاول الفهم - فلا يضيع نداء
        # ولو كانت صيغته مجهولة تماماً.
        record = Inbox._qd_capture(
            client, code, raw_body,
            Inbox._qd_safe_headers(request.httprequest.headers.items()),
            request.httprequest.remote_addr)
        if not record:
            raise BadRequest('بلغ هذا التاجر سقف الالتقاط', 429)

        order = record._qd_try_map()
        payload = {'status': 'accepted', 'intake_id': record.id}
        if order:
            payload.update(self._intake_result(order))
        else:
            payload['note'] = ('استُلم وحُفظ - بانتظار مُحوّل الصيغة. '
                               'لن يضيع، ويُعاد تحويله لاحقاً.')
        return _json_response(payload, 202)

    def _intake_result(self, order):
        return {
            'status': 'success',
            'tracking_number': order.name,
            # الرمز يُسلَّم هنا مرة واحدة ليعرضه التاجر لعميله - وأُزيل
            # من إبلاغات تغيير الحالة.
            'delivery_otp': order.delivery_otp,
            # ورابط التتبع: يضعه التاجر في رسالته لعميله، فيصل الرمز
            # إلى صاحبه بدل أن يبقى في سجلات التاجر.
            'tracking_url': order.tracking_url,
            'assigned_driver': order.driver_id.name or 'searching',
            'state': order.state,
        }

    # ==================================================================
    # 2. غرفة العمليات
    # ==================================================================
    @http.route('/api/v1/qcommerce/dashboard', type='jsonrpc', auth='user',
                readonly=True)
    def get_dashboard_data(self, client_id=None):
        """غرفة العمليات - كلها أو لسوبرماركت واحد.

        بلا client_id تُرجع العرض العام كما كانت. ومعه تُرشَّح
        **الطلبات** وحدها: المندوب مشترك بين العثيم وبندة في نفس
        الوردية، فإخفاء من يعمل لغيرها يُفقد رؤية الطاقة المتاحة -
        وهي نصف فائدة الخريطة، إذ منها يُسنَد يدوياً. يبقى الجميع
        ظاهرين، ومن هو في مهمة لشركة أخرى يُعلَّم بذلك.
        """
        if not request.env.user.has_group(DISPATCHER_GROUP):
            raise AccessError(_('غرفة العمليات محصورة بفريق التوصيل.'))

        Order = request.env['quick.delivery.order'].sudo()
        client = request.env['res.partner'].sudo().browse(int(client_id)) \
            if client_id else request.env['res.partner'].browse()
        if client_id and (not client.exists()
                          or not client.is_qcommerce_client):
            raise BadRequest('سوبرماركت غير معروف', 404)

        scope = [('client_id', '=', client.id)] if client else []
        active_orders = Order.search(
            [('state', 'in', Order.OPEN_STATES)] + scope)
        now = fields.Datetime.now()

        orders_list = []
        for order in active_orders:
            remaining_sec = int((order.sla_deadline - now).total_seconds()) \
                if order.sla_deadline else 0
            orders_list.append({
                'id': order.id,
                'name': order.name,
                'merchant_order_id': order.merchant_order_id,
                'client_name': order.client_id.name,
                'store_name': order.store_name,
                'store_lat': order.store_lat,
                'store_lng': order.store_lng,
                'customer_name': order.customer_name,
                'customer_lat': order.customer_lat,
                'customer_lng': order.customer_lng,
                'driver_id': order.driver_id.id or False,
                'driver_name': order.driver_id.name or 'بانتظار مندوب!',
                'state': order.state,
                'cod_amount': order.cod_amount,
                'remaining_minutes': round(remaining_sec / 60, 1),
                'is_urgent': remaining_sec < 600,
            })

        drivers = request.env['quick.delivery.driver'].sudo().search([])
        # لمن يعمل كل مندوب الآن: نداء واحد لكل الطلبات الحيّة، لا
        # استعلام لكل مندوب.
        busy_for = {}
        for order in Order.search([('state', 'in', Order.OPEN_STATES),
                                   ('driver_id', '!=', False)]):
            busy_for.setdefault(order.driver_id.id, order.client_id)
        drivers_list = []
        for driver in drivers:
            engaged = busy_for.get(driver.id)
            drivers_list.append({
                'id': driver.id,
                'name': driver.name,
                'status': driver.driver_status,
                'lat': driver.current_lat,
                'lng': driver.current_lng,
                'cod_balance': driver.cod_custody_balance,
                'today_orders': driver.today_delivered_count,
                'busy_for': engaged.name if engaged else '',
                # في مهمة لشركة أخرى: يظهر باهتاً على الخريطة، فتُرى
                # الطاقة ولا يختلط عمل الشركات.
                'busy_for_other': bool(client and engaged
                                       and engaged.id != client.id),
            })

        day_start = Order._day_start_utc_for_env()
        today_delivered = Order.search([
            ('state', '=', 'delivered'),
            ('delivered_at', '>=', day_start),
        ] + scope)
        total_cod_today = sum(today_delivered.filtered(
            lambda rec: rec.payment_method == 'COD').mapped('cod_amount'))

        return {
            # اسم الشركة المختارة ليعرف المستخدم ما ينظر إليه، وقائمة
            # الشركات للتنقّل بلا رجوع.
            'scope': {
                'client_id': client.id or False,
                'client_name': client.name or '',
                'clients': [{'id': rec.id, 'name': rec.name} for rec in
                            request.env['res.partner'].sudo().search(
                                [('is_qcommerce_client', '=', True)],
                                order='name')],
            },
            'kpis': {
                'active_count': len(active_orders),
                'unassigned_count': len(active_orders.filtered(
                    lambda rec: rec.state == 'searching_driver')),
                'online_drivers': len(drivers.filtered(
                    lambda drv: drv.driver_status == 'online')),
                'busy_drivers': len(drivers.filtered(
                    lambda drv: drv.driver_status == 'busy')),
                'delivered_today': len(today_delivered),
                'total_cod_today': total_cod_today,
            },
            'orders': orders_list,
            'drivers': drivers_list,
        }

    @http.route('/api/v1/qcommerce/manual_assign', type='jsonrpc',
                auth='user')
    def manual_assign_driver(self, order_id, driver_id):
        if not request.env.user.has_group(DISPATCHER_GROUP):
            raise AccessError(_('التوزيع محصور بفريق التوصيل.'))

        order = request.env['quick.delivery.order'].sudo().browse(
            int(order_id))
        driver = request.env['quick.delivery.driver'].sudo().browse(
            int(driver_id))
        if not order.exists() or not driver.exists():
            return {'status': 'error', 'error': 'Not found'}
        if not driver.active:
            return {'status': 'error', 'error': 'هذا المندوب موقوف'}
        if order.state not in ('searching_driver', 'driver_assigned'):
            return {'status': 'error',
                    'error': 'لا يمكن تغيير المندوب بعد استلام الطلب'}

        try:
            # write() يحرّر المندوب السابق ويتحقّق من الانتقال.
            # والإسناد اليدوي تجاوزٌ مقصود: يرفع علامة "يحتاج غرفة
            # العمليات" ويعتبر الطلب مقبولاً - من أسنده إنسانٌ يعرف
            # ما يفعل، فلا يُسحب منه بعد دقيقة.
            order.write({
                'driver_id': driver.id,
                'state': 'driver_assigned',
                'needs_attention': False,
                'accepted_at': fields.Datetime.now(),
            })
            driver.write({'driver_status': 'busy'})
        except (UserError, ValidationError) as error:
            return {'status': 'error',
                    'error': error.args[0] if error.args else 'خطأ'}
        return {'status': 'success'}

    # ==================================================================
    # 2-ب. صفحة تتبع العميل النهائي
    # ==================================================================
    # الحارس الوحيد هو الرمز في الرابط. لا رقم تتبع متسلسل: QCK-2026-
    # 000047 يُخمَّن، فيقرأ أي أحد رمز تسليم أي طلب ويستلم بدل صاحبه.
    TRACK_STEPS = (
        ('جارٍ تجهيز طلبك', 'نبحث عن أقرب مندوب إليك'),
        ('تم تعيين مندوب', 'في طريقه إلى الفرع'),
        ('المندوب في الفرع', 'يستلم طلبك الآن'),
        ('في الطريق إليك', 'أبقِ جوالك قريباً'),
        ('تم التسليم', ''),
    )

    def _tracked_order(self, token):
        token = (token or '').strip()
        if len(token) < 16:
            # رمز قصير = محاولة تخمين، لا رابط حقيقي. لا نبحث أصلاً.
            return request.env['quick.delivery.order'].browse()
        return request.env['quick.delivery.order'].sudo().search(
            [('tracking_token', '=', token)], limit=1)

    @http.route('/track/<string:token>', type='http', auth='public',
                website=False, readonly=True)
    def public_tracking_page(self, token, **kwargs):
        order = self._tracked_order(token)
        if not order:
            return request.render('quick_delivery.tracking_missing_template',
                                  {}, status=404)
        data = order._public_tracking_data()

        steps = []
        for index, (title, note) in enumerate(self.TRACK_STEPS):
            if data['state'] in ('failed', 'cancelled'):
                css = 'is-done' if index < data['step'] else ''
            elif data['is_delivered'] or index < data['step']:
                css = 'is-done'
            elif index == data['step']:
                css = 'is-current'
            else:
                css = ''
            steps.append({'title': title, 'note': note, 'cls': css})

        status_class = 'tk-card tk-status'
        if data['state'] in ('failed', 'cancelled'):
            status_class += ' tk-status--failed'
        elif data['is_delivered']:
            status_class += ' tk-status--done'
        elif data['is_open'] and not data['remaining_seconds']:
            status_class += ' tk-status--late'

        return request.render('quick_delivery.tracking_page_template', {
            'd': data, 'steps': steps, 'token': token,
            'status_class': status_class,
        })

    @http.route('/api/v1/track/<string:token>', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False,
                readonly=True)
    @api_endpoint
    def public_tracking_data(self, token, **kwargs):
        order = self._tracked_order(token)
        if not order:
            raise BadRequest('Not found', 404)
        return _json_response(order._public_tracking_data())

    # ==================================================================
    # 3. تطبيق المندوب - ويب مستقل (PWA)
    # ==================================================================
    @http.route(['/driver', '/driver/'], type='http', auth='public',
                website=False, readonly=True)
    def driver_app_shell(self, **kwargs):
        """هيكل التطبيق - عامٌّ وخالٍ من أي بيان.

        لا auth='user': المندوب ليس مستخدم أودو. والصفحة نفسها لا تحمل
        اسماً ولا طلباً - الدخول ثم الـAPI يملآنها، فلا يُسرَّب شيء لمن
        يفتح الرابط.
        """
        return request.render('quick_delivery.driver_app_template', {})

    @http.route('/driver/manifest.json', type='http', auth='public',
                methods=['GET'], readonly=True)
    def driver_app_manifest(self, **kwargs):
        """ملف التعريف الذي يجعله تطبيقاً مُثبَّتاً على الشاشة الرئيسية."""
        manifest = {
            'name': 'مندوب التوصيل السريع',
            'short_name': 'المندوب',
            'description': 'تطبيق مندوب التوصيل الفوري - استلام وتسليم '
                           'وإثبات تسليم',
            'lang': 'ar',
            'dir': 'rtl',
            'start_url': '/driver',
            'scope': '/driver',
            'display': 'standalone',
            'orientation': 'portrait',
            'background_color': '#0f172a',
            'theme_color': '#0f172a',
            'icons': [
                {'src': '/quick_delivery/static/src/driver_app/icon-192.png',
                 'sizes': '192x192', 'type': 'image/png'},
                {'src': '/quick_delivery/static/src/driver_app/icon-512.png',
                 'sizes': '512x512', 'type': 'image/png'},
                {'src': '/quick_delivery/static/src/driver_app/icon-512.png',
                 'sizes': '512x512', 'type': 'image/png',
                 'purpose': 'maskable'},
            ],
        }
        return Response(
            json.dumps(manifest, ensure_ascii=False),
            content_type='application/manifest+json;charset=utf-8')

    @http.route('/driver/sw.js', type='http', auth='public', methods=['GET'],
                readonly=True)
    def driver_app_service_worker(self, **kwargs):
        """العامل الخدمي يُخدَم من هنا لا من static.

        السبب ترويسة Service-Worker-Allowed: ملفٌ داخل /static نطاقه
        /static فلا يتحكم بـ/driver. وهذا ما يجعل التطبيق يفتح على شبكة
        متقطعة بدل صفحة "لا يوجد اتصال".
        """
        with file_open('%s/sw.js' % DRIVER_APP_DIR, 'r') as handle:
            content = handle.read()
        return Response(content, content_type='text/javascript;charset=utf-8',
                        headers=[('Service-Worker-Allowed', '/driver'),
                                 ('Cache-Control', 'no-cache')])

    # ------------------------------------------------------------------
    # مسارات الـAPI لتطبيق المندوب
    # ------------------------------------------------------------------
    @http.route('/api/v1/driver/login', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_login(self, **kwargs):
        """جوال + رمز سري ← رمز جلسة.

        الرمز السري مُعمّى في قاعدة البيانات، والمحاولات الفاشلة تُقفل
        الحساب: أربعة إلى ستة أرقام تُخمَّن في دقائق بلا قفل.
        """
        # حدّان: على العنوان وعلى الرقم. القفل بعد خمس محاولات يحمي
        # مندوباً بعينه، وهذا يحمي من تجريب رقم سرّي واحد على ألف رقم -
        # ولا يُحتسب فشلٌ على رقم غير مسجَّل أصلاً.
        _throttle('login', request.httprequest.remote_addr)
        data = _body_json()
        phone = str(data.get('phone') or '').strip()
        pin = str(data.get('pin') or '').strip()
        if not phone or not pin:
            raise BadRequest('يُرجى إدخال رقم الجوال ورمز الدخول', 400)
        _throttle('login', 'phone-%s' % request.env[
            'quick.delivery.driver'].sudo()._phone_key(phone))

        Driver = request.env['quick.delivery.driver'].sudo()
        locked_minutes = Driver._qd_login_lock_minutes(phone)
        if locked_minutes:
            raise BadRequest(
                'الدخول مقفول بعد محاولات خاطئة - أعد المحاولة بعد %d دقيقة '
                'أو راجع غرفة العمليات.' % locked_minutes, 429)

        driver = Driver._qd_authenticate(phone, pin)
        if not driver:
            # رسالة واحدة للرقم الخاطئ وللرمز الخاطئ: التمييز يُفشي من
            # هو مندوب ومن ليس.
            raise BadRequest('رقم الجوال أو رمز الدخول غير صحيح', 401)

        device = request.httprequest.headers.get('User-Agent', '')
        token = driver._qd_open_session(device)
        return _json_response({
            'status': 'success',
            'token': token,
            'expires_at': fields.Datetime.to_string(driver.session_expiry),
            'driver': {
                'id': driver.id,
                'name': driver.name,
                'status': driver.driver_status,
            },
        })

    @http.route('/api/v1/driver/logout', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_logout(self, **kwargs):
        driver = _session_driver()
        # الخروج من التطبيق انصرافٌ أيضاً - إلا إن كان عليه طلب حيّ،
        # فحالته تبقى "في مهمة" حتى يُغلق.
        if not driver._qd_has_open_order():
            driver.sudo().write({'driver_status': 'offline'})
        driver._qd_close_session()
        return _json_response({'status': 'success'})

    @http.route('/api/v1/driver/state', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_state(self, **kwargs):
        """نداء واحد: يُحدِّث الموقع والحالة، ويُعيد الطلب والمحفظة.

        النسخة السابقة كانت أربعة مسارات (ping، active-order، وزوج
        jsonrpc للويب) - أي رحلات متعددة على شبكة الجوال كل ثماني ثوان.
        """
        driver = _session_driver()
        _throttle('driver', 'driver-%s' % driver.id)
        data = _body_json()
        return _json_response(self._driver_state(
            driver, data.get('lat'), data.get('lng'),
            data.get('set_status')))

    @http.route('/api/v1/driver/order/<int:order_id>/accept',
                type='http', auth='none', methods=['POST'], csrf=False,
                save_session=False, readonly=False)
    @api_endpoint
    def driver_accept_order(self, order_id, **kwargs):
        """تأكيد أخذ الطلب - يوقف عدّاد السحب."""
        driver = _session_driver()
        order = _order_of_driver(driver, order_id)
        order._qd_accept(driver)
        return _json_response(self._driver_state(driver))

    @http.route('/api/v1/driver/order/<int:order_id>/decline',
                type='http', auth='none', methods=['POST'], csrf=False,
                save_session=False, readonly=False)
    @api_endpoint
    def driver_decline_order(self, order_id, **kwargs):
        """ردّ الطلب صراحةً.

        الرفض أصدق من الصمت: يُحرّر الطلب فوراً لمندوب آخر بدل
        انتظار المهلة كاملةً.
        """
        driver = _session_driver()
        order = _order_of_driver(driver, order_id)
        data = _body_json()
        order._qd_decline(driver, (data.get('reason') or '')[:200])
        _logger.info('ردّ المندوب %s (id=%s) الطلب %s: %s',
                     driver.name, driver.id, order.name,
                     data.get('reason') or '(بلا سبب)')
        # لا يُعاد البحث هنا: المجدول يلتقطه خلال دقيقة، وإعادة
        # الإسناد داخل نداء المندوب قد تُعيده إليه إن كان الوحيد.
        return _json_response(self._driver_state(driver))

    @http.route('/api/v1/driver/push/key', type='http', auth='none',
                methods=['GET'], csrf=False, save_session=False,
                readonly=True)
    @api_endpoint
    def driver_push_key(self, **kwargs):
        """المفتاح العام لـVAPID - عامٌّ بطبيعته، فلا جلسة له.

        التطبيق يحتاجه قبل الاشتراك، والاشتراك يسبق تسجيل الدخول
        أحياناً (يُسأل الإذن أول فتح).
        """
        return _json_response({
            'public_key': request.env['quick.delivery.push.config'].sudo(
            )._vapid_public(),
        })

    @http.route('/api/v1/driver/push/subscribe', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_push_subscribe(self, **kwargs):
        """يربط جهاز المندوب بحسابه.

        الاشتراك من المتصفح يُعرَّف بنقطة الدفع وحدها، ومن يملك الجلسة
        هو صاحبها - فلا يُقبل تسجيل جهاز باسم مندوب آخر.
        """
        driver = _session_driver()
        _throttle('driver', 'push-%s' % driver.id)
        data = _body_json()
        keys = data.get('keys') or {}
        device = request.env['quick.delivery.push.subscription'].sudo(
        )._register_device(
            driver,
            data.get('endpoint'),
            keys.get('p256dh'),
            keys.get('auth'),
            request.httprequest.headers.get('User-Agent', ''),
        )
        return _json_response({'status': 'subscribed', 'device_id': device.id})

    @http.route('/api/v1/driver/push/unsubscribe', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_push_unsubscribe(self, **kwargs):
        driver = _session_driver()
        data = _body_json()
        endpoint = (data.get('endpoint') or '').strip()
        devices = request.env['quick.delivery.push.subscription'].sudo(
        ).search([('driver_id', '=', driver.id),
                  ('endpoint', '=', endpoint)])
        devices.unlink()
        return _json_response({'status': 'unsubscribed'})

    @http.route('/api/v1/driver/order/<int:order_id>/status', type='http',
                auth='none', methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_update_status(self, order_id, **kwargs):
        driver = _session_driver()
        data = _body_json()
        order = _order_of_driver(driver, order_id)
        self._apply_driver_state(
            driver, order, data.get('state'), data.get('otp_code'),
            data.get('photo_base64'), data.get('failure_reason'),
            data.get('failure_notes'))
        return _json_response({'status': 'success', 'state': order.state,
                               'wallet': _wallet_payload(driver)})

    # ------------------------------------------------------------------
    # منطق مشترك
    # ------------------------------------------------------------------
    def _write_driver_presence(self, driver, lat=None, lng=None,
                               set_status=None):
        vals = {'last_ping': fields.Datetime.now()}
        if lat is not None and lng is not None:
            vals['current_lat'] = _coordinate(lat, 'lat')
            vals['current_lng'] = _coordinate(lng, 'lng')
        if set_status is not None:
            # الحالة من الطلب كانت تُكتب كما وصلت: قيمة غير موجودة في
            # القائمة تُخرج خطأ 500، و"busy" من التطبيق تُفسد التوزيع.
            if set_status not in ('online', 'offline'):
                raise BadRequest('حالة مندوب غير مسموحة: %r' % set_status)
            if set_status == 'offline' and driver._qd_has_open_order():
                raise BadRequest('لا يمكن الانصراف وعليك طلب لم يُغلق بعد')
            # بدء وردية ومعه طلب حيّ (عاد من انقطاع، أو فتح التطبيق على
            # جهاز آخر) يعني "في مهمة" لا "متاح": الإسناد كان يتجنّبه
            # بالقفل، لكن غرفة العمليات كانت تراه شاغراً في العدّاد
            # والخريطة فتنتظر منه ما لا يستطيع.
            if set_status == 'online' and driver._qd_has_open_order():
                vals['driver_status'] = 'busy'
            else:
                vals['driver_status'] = set_status
        driver.sudo().write(vals)

    def _driver_state(self, driver, lat=None, lng=None, set_status=None):
        self._write_driver_presence(driver, lat, lng, set_status)
        Order = request.env['quick.delivery.order'].sudo()
        order = Order.search([
            ('driver_id', '=', driver.id),
            ('state', 'in', ('driver_assigned', 'arrived_at_store',
                             'picked_up')),
        ], limit=1)
        payload = {
            'status': 'success',
            'has_order': bool(order),
            'driver_name': driver.name,
            'driver_status': driver.driver_status,
            'wallet': _wallet_payload(driver),
        }
        if order:
            payload['order'] = _order_payload(order)
            # أول ظهور للطلب على جواله: هذه لحظة "علم به" التي نقيس
            # بها زمن وصول الإشعار. تُكتب مرة واحدة لا في كل استطلاع.
            order._mark_seen_by_driver()
        return payload

    def _apply_driver_state(self, driver, order, new_state, otp_code=None,
                            photo_base64=None, failure_reason=None,
                            failure_notes=None):
        """آلة الحالات في النموذج هي الحاكم - لا نص الطلب.

        والسجل هنا هو أثر المراجعة: المندوب ليس مستخدم أودو، فلا
        create_uid ولا write_uid يحمل اسمه. كل انتقال يُسجَّل باسمه
        ورقمه وعنوانه.
        """
        _logger.info(
            'تطبيق المندوب: %s (id=%s) ← الطلب %s: %s ← %s [IP %s]',
            driver.name, driver.id, order.name, new_state, order.state,
            request.httprequest.remote_addr)
        if new_state == 'delivered':
            order.action_mark_delivered(otp_code=otp_code,
                                        photo_base64=photo_base64)
        elif new_state == 'failed':
            order.action_mark_failed(failure_reason=failure_reason,
                                     failure_notes=failure_notes)
        elif new_state in ('arrived_at_store', 'picked_up'):
            order.write({'state': new_state})
        else:
            raise BadRequest('حالة غير مسموحة من تطبيق المندوب: %r'
                             % new_state)
