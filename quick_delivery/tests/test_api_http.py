# -*- coding: utf-8 -*-
"""اختبارات الـAPI وتطبيق المندوب عبر HTTP حقيقي - لا باستدعاء الدوال.

السبب: أخطر ما في مسارات الويب لا يظهر إلا عبر HTTP - رمز الحالة
المُعاد (500 بدل 400)، وتتبّع الكود الذي كان يُسلَّم للعثيم وبندة،
وفحوص الصلاحية على المسارات، وترويسة العامل الخدمي.
"""
import json

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

API_URL = '/api/v1/qcommerce/orders'
LOGIN_URL = '/api/v1/driver/login'
STATE_URL = '/api/v1/driver/state'
LOGOUT_URL = '/api/v1/driver/logout'


@tagged('post_install', '-at_install')
class TestMerchantApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env['res.partner'].create({
            'name': 'سوبرماركت الـAPI',
            'is_qcommerce_client': True,
            'api_key': 'HTTPKEY-1',
        })
        cls.env['quick.delivery.driver'].create({
            'name': 'مندوب الـAPI', 'phone': '0552220001', 'pin': '1234',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753,
        })
        cls.env.cr.flush()

    def _post(self, url, body, headers=None, raw=False):
        payload = body if raw else json.dumps(body)
        return self.url_open(
            url, data=payload.encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     **(headers or {})})

    def _order_body(self, order_id='API-1', **over):
        body = {
            'order_id': order_id,
            'store': {'store_name': 'فرع العليا', 'store_code': 'OL',
                      'lat': 24.7100, 'lng': 46.6700},
            'customer': {'name': 'عميل', 'phone': '0550000000',
                         'lat': 24.7200, 'lng': 46.6800},
            'payment': {'method': 'PREPAID'},
        }
        body.update(over)
        return body

    # ------------------------------------------------------------------
    def test_fixture_is_visible_in_process(self):
        """تشخيص: هل مفتاح الـAPI مكتوب فعلاً وقابلاً للبحث؟

        يفصل "الحقل لم يُحفظ" عن "طلب HTTP في معاملة لا تراه" - وبدونه
        يبدو فشل اختبارات HTTP كخلل في الكود وهو ليس كذلك.
        """
        found = self.env['res.partner'].sudo().search([
            ('api_key', '=', 'HTTPKEY-1'),
            ('is_qcommerce_client', '=', True),
        ], limit=1)
        self.assertTrue(found, 'مفتاح الـAPI غير قابل للبحث داخل المعاملة')

    def test_valid_order_is_created(self):
        response = self._post(API_URL, self._order_body(),
                              {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(data['tracking_number'])
        self.assertRegex(data['delivery_otp'], r'^\d{6}$')

    def test_duplicate_order_returns_the_same_tracking_number(self):
        first = self._post(API_URL, self._order_body('IDEM-1'),
                           {'X-API-Key': 'HTTPKEY-1'})
        second = self._post(API_URL, self._order_body('IDEM-1'),
                            {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['tracking_number'],
                         second.json()['tracking_number'])

    def test_bad_api_key_is_rejected(self):
        response = self._post(API_URL, self._order_body(),
                              {'X-API-Key': 'WRONG'})
        self.assertEqual(response.status_code, 401)

    def test_missing_api_key_is_rejected(self):
        response = self._post(API_URL, self._order_body())
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # الأهم: خطأ في المدخلات = 400 مفهوم، لا 500 بتتبّع كود
    # ------------------------------------------------------------------
    def test_malformed_json_returns_400_not_500(self):
        response = self._post(API_URL, '{ليس JSON',
                              {'X-API-Key': 'HTTPKEY-1'}, raw=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn('JSON', response.json()['error'])

    def test_missing_required_fields_returns_400(self):
        response = self._post(API_URL, {'order_id': 'X-1'},
                              {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('store_name', response.json()['error'])

    def test_missing_coordinates_returns_400(self):
        body = self._order_body('NOGEO-1')
        body['store'].pop('lat')
        response = self._post(API_URL, body, {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 400)

    def test_non_numeric_coordinates_returns_400(self):
        body = self._order_body('BADGEO-1')
        body['store']['lat'] = 'شمال'
        response = self._post(API_URL, body, {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 400)

    def test_unknown_payment_method_returns_400(self):
        body = self._order_body('PAY-1', payment={'method': 'BITCOIN'})
        response = self._post(API_URL, body, {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 400)

    def test_cod_without_amount_returns_400_not_500(self):
        body = self._order_body('COD-1', payment={'method': 'COD'})
        response = self._post(API_URL, body, {'X-API-Key': 'HTTPKEY-1'})
        self.assertEqual(response.status_code, 400)

    def test_no_python_traceback_leaks_to_the_merchant(self):
        """ما كان يصل العثيم/بندة عند أي حقل ناقص."""
        response = self._post(API_URL, '{', {'X-API-Key': 'HTTPKEY-1'},
                              raw=True)
        body = response.text
        for leak in ('Traceback', 'odoo.exceptions', 'File "',
                     'quick_delivery/'):
            self.assertNotIn(leak, body,
                             'الرد يسرّب تفاصيل الكود: %s' % leak)


@tagged('post_install', '-at_install')
class TestDriverApi(HttpCase):
    """تطبيق المندوب: دخول بجوال ورمز سري، وجلسة تنتهي.

    القديم كان رمزاً نصّياً أبدياً في ترويسة Bearer، على مستخدم أودو
    داخلي مدفوع الرخصة.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Driver = cls.env['quick.delivery.driver']
        cls.Driver.sudo().with_context(active_test=False).search(
            []).write({'driver_status': 'offline'})
        cls.client_partner = cls.env['res.partner'].create({
            'name': 'سوبرماركت المندوب', 'is_qcommerce_client': True,
            'api_key': 'HTTPKEY-D'})
        cls.driver = cls.Driver.create({
            'name': 'مندوب HTTP', 'phone': '0553330001', 'pin': '4321',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753,
        })
        cls.other = cls.Driver.create({
            'name': 'مندوب آخر', 'phone': '0553330002', 'pin': '4321',
            'driver_status': 'offline'})
        cls.env.cr.flush()

    # ------------------------------------------------------------------
    def _post(self, url, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer %s' % token
        return self.url_open(url, data=json.dumps(body or {}).encode('utf-8'),
                             headers=headers)

    def _login(self, phone='0553330001', pin='4321'):
        return self._post(LOGIN_URL, {'phone': phone, 'pin': pin})

    def _token(self):
        response = self._login()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['token']

    def _make_order(self, merchant_order_id, driver):
        order = self.env['quick.delivery.order'].create({
            'client_id': self.client_partner.id,
            'merchant_order_id': merchant_order_id,
            'store_name': 'فرع', 'store_lat': 24.71, 'store_lng': 46.67,
            'customer_name': 'عميل', 'customer_phone': '0550000000',
            'customer_lat': 24.72, 'customer_lng': 46.68,
            'driver_id': driver.id, 'state': 'driver_assigned',
        })
        self.env.cr.flush()
        return order

    # ---------------------------------------------------------- الدخول
    def test_login_with_correct_pin_returns_a_session(self):
        response = self._login()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data['token'])
        self.assertGreaterEqual(len(data['token']), 32)
        self.assertEqual(data['driver']['name'], 'مندوب HTTP')
        self.assertTrue(data['expires_at'], 'الجلسة بلا انتهاء = رمز أبدي')

    def test_login_with_wrong_pin_is_rejected(self):
        self.assertEqual(self._login(pin='0000').status_code, 401)

    def test_login_with_an_unknown_phone_is_rejected(self):
        self.assertEqual(self._login(phone='0569999999').status_code, 401)

    def test_the_two_failures_look_identical(self):
        """التمييز بين "رقم غير مسجّل" و"رمز خاطئ" يُفشي من هو مندوب."""
        unknown = self._login(phone='0569999999').json()
        wrong_pin = self._login(pin='0000').json()
        self.assertEqual(unknown['error'], wrong_pin['error'])

    def test_empty_body_is_rejected_not_crashed(self):
        self.assertEqual(self._post(LOGIN_URL, {}).status_code, 400)

    def test_five_wrong_attempts_lock_the_login(self):
        for _unused in range(5):
            self._login(pin='0000')
        locked = self._login()
        self.assertEqual(locked.status_code, 429, locked.text)

    def test_login_with_an_international_phone_format(self):
        """الضابط العملي: المندوب يكتب رقمه كما يحفظه."""
        self.assertEqual(self._login(phone='+966553330001').status_code, 200)

    # --------------------------------------------------------- الجلسة
    def test_state_without_a_token_is_rejected(self):
        response = self._post(STATE_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get('code'), 'session_expired')

    def test_state_with_a_bogus_token_is_rejected(self):
        self.assertEqual(self._post(STATE_URL, token='not-a-real-token').status_code,
                         401)

    def test_state_for_a_logged_in_driver_works(self):
        """الضابط المقابل: المندوب الحقيقي يُخدَم."""
        response = self._post(STATE_URL, token=self._token())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn('wallet', body)
        self.assertEqual(body['driver_name'], 'مندوب HTTP')

    def test_state_writes_the_position(self):
        token = self._token()
        response = self._post(STATE_URL,
                              {'lat': 24.72, 'lng': 46.68}, token=token)
        self.assertEqual(response.status_code, 200)
        self.driver.invalidate_recordset()
        self.assertAlmostEqual(self.driver.current_lat, 24.72, places=4)

    def test_an_invalid_status_is_refused(self):
        """الحالة كانت تُكتب كما وصلت - قيمة خارج القائمة = 500."""
        response = self._post(STATE_URL, {'set_status': 'teleporting'},
                              token=self._token())
        self.assertEqual(response.status_code, 400)

    def test_going_offline_and_online_works(self):
        token = self._token()
        self.assertEqual(
            self._post(STATE_URL, {'set_status': 'offline'},
                       token=token).json()['driver_status'], 'offline')
        self.assertEqual(
            self._post(STATE_URL, {'set_status': 'online'},
                       token=token).json()['driver_status'], 'online')

    def test_going_online_with_a_live_order_reports_busy(self):
        """عاد من انقطاع وعليه طلب: غرفة العمليات كانت تراه شاغراً في
        العدّاد والخريطة فتنتظر منه ما لا يستطيع."""
        self._make_order('BUSY-HTTP-1', self.driver)
        body = self._post(STATE_URL, {'set_status': 'online'},
                          token=self._token()).json()
        self.assertEqual(body['driver_status'], 'busy')

    def test_going_online_without_an_order_reports_online(self):
        """الضابط المقابل: من لا طلب عليه يصير متاحاً فعلاً."""
        body = self._post(STATE_URL, {'set_status': 'online'},
                          token=self._token()).json()
        self.assertEqual(body['driver_status'], 'online')

    def test_cannot_go_offline_with_a_live_order(self):
        self._make_order('OFF-HTTP-1', self.driver)
        response = self._post(STATE_URL, {'set_status': 'offline'},
                              token=self._token())
        self.assertEqual(response.status_code, 400)

    def test_logout_kills_the_session(self):
        token = self._token()
        self.assertEqual(self._post(LOGOUT_URL, token=token).status_code, 200)
        after = self._post(STATE_URL, token=token)
        self.assertEqual(after.status_code, 401,
                         'الرمز ما زال يعمل بعد الخروج')

    def test_revoking_from_odoo_kills_the_live_session(self):
        token = self._token()
        self.driver.action_revoke_sessions()
        self.env.cr.flush()
        self.assertEqual(self._post(STATE_URL, token=token).status_code, 401)

    # ---------------------------------------------------------- الطلبات
    def test_the_assigned_order_reaches_the_driver(self):
        order = self._make_order('MINE-HTTP-1', self.driver)
        body = self._post(STATE_URL, token=self._token()).json()
        self.assertTrue(body['has_order'])
        self.assertEqual(body['order']['id'], order.id)
        self.assertEqual(body['order']['customer_phone'], '0550000000')

    def test_driver_cannot_touch_another_drivers_order(self):
        order = self._make_order('OTHER-HTTP-1', self.other)
        response = self._post(
            '/api/v1/driver/order/%d/status' % order.id,
            {'state': 'delivered', 'otp_code': '000000'},
            token=self._token())
        self.assertEqual(response.status_code, 403)

    def test_the_full_delivery_path_over_http(self):
        order = self._make_order('PATH-HTTP-1', self.driver)
        token = self._token()
        url = '/api/v1/driver/order/%d/status' % order.id

        self.assertEqual(
            self._post(url, {'state': 'arrived_at_store'},
                       token=token).status_code, 200)
        self.assertEqual(
            self._post(url, {'state': 'picked_up'}, token=token).status_code,
            200)
        order.invalidate_recordset()
        otp = order.sudo().delivery_otp
        done = self._post(url, {'state': 'delivered', 'otp_code': otp},
                          token=token)
        self.assertEqual(done.status_code, 200, done.text)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'delivered')
        self.assertEqual(order.pod_method, 'otp')

    def test_skipping_the_pickup_is_refused_with_400(self):
        order = self._make_order('SKIP-HTTP-1', self.driver)
        response = self._post(
            '/api/v1/driver/order/%d/status' % order.id,
            {'state': 'delivered', 'otp_code': order.sudo().delivery_otp},
            token=self._token())
        self.assertEqual(response.status_code, 400, response.text)

    def test_a_wrong_otp_is_refused_with_400(self):
        order = self._make_order('OTP-HTTP-1', self.driver)
        token = self._token()
        url = '/api/v1/driver/order/%d/status' % order.id
        self._post(url, {'state': 'arrived_at_store'}, token=token)
        self._post(url, {'state': 'picked_up'}, token=token)
        response = self._post(url, {'state': 'delivered',
                                    'otp_code': '000000'}, token=token)
        self.assertEqual(response.status_code, 400)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'picked_up')


@tagged('post_install', '-at_install')
class TestDriverWebApp(HttpCase):
    """الصفحة نفسها: عامة، وبلا أي بيان، وقابلة للتثبيت."""

    def test_the_app_page_is_public(self):
        """لا auth='user': المندوب ليس مستخدم أودو، ولو كان لطُلب منه
        تسجيل دخول أودو كامل على جواله."""
        response = self.url_open('/driver')
        self.assertEqual(response.status_code, 200)
        self.assertIn('تطبيق مندوب التوصيل', response.text)

    def test_the_page_carries_no_data(self):
        """الصفحة عامة، فلا يجوز أن تحمل اسم مندوب ولا طلباً."""
        self.env['quick.delivery.driver'].create({
            'name': 'مندوب سرّي جداً', 'phone': '0554440001'})
        self.env.cr.flush()
        body = self.url_open('/driver').text
        self.assertNotIn('مندوب سرّي جداً', body)

    def test_the_manifest_is_served(self):
        response = self.url_open('/driver/manifest.json')
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest['start_url'], '/driver')
        self.assertTrue(manifest['icons'])

    def test_the_service_worker_carries_its_scope_header(self):
        """بلا هذه الترويسة لا يتحكم العامل بـ/driver، فلا يفتح
        التطبيق على شبكة متقطعة."""
        response = self.url_open('/driver/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Service-Worker-Allowed'),
                         '/driver')
        self.assertIn('javascript', response.headers.get('Content-Type', ''))

    def test_the_app_assets_are_served_and_have_no_cdn(self):
        """النسخة السابقة كانت تجلب Bootstrap وصوت التنبيه من الإنترنت:
        حجب النطاق أو انقطاعه يُفقد التطبيق شكله وصوته."""
        page = self.url_open('/driver').text
        for cdn in ('jsdelivr', 'unpkg', 'cdnjs', 'googleapis',
                    'actions.google.com', 'bootstrap'):
            self.assertNotIn(cdn, page, 'الصفحة ما زالت تعتمد على %s' % cdn)
        for asset in ('app.css', 'app.js'):
            url = '/quick_delivery/static/src/driver_app/%s' % asset
            self.assertEqual(self.url_open(url).status_code, 200, asset)


@tagged('post_install', '-at_install')
class TestDashboardAccess(HttpCase):
    """الداش بورد والتوزيع كانا auth='user' بلا فحص مجموعة: أي مستخدم
    داخلي يقرأ جوال كل عميل وموقعه، ويعيد إسناد أي طلب."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_password = 'plainpass123'
        cls.plain = cls.env['res.users'].create({
            'name': 'مستخدم عادي HTTP', 'login': 'http_plain',
            'password': cls.plain_password,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.dispatcher_password = 'disppass123'
        cls.dispatcher = cls.env['res.users'].create({
            'name': 'غرفة العمليات HTTP', 'login': 'http_dispatcher',
            'password': cls.dispatcher_password,
            'group_ids': [(6, 0, [
                cls.env.ref('quick_delivery.group_qd_dispatcher').id])],
        })
        cls.env.cr.flush()

    def _call_dashboard(self):
        return self.url_open(
            '/api/v1/qcommerce/dashboard',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                             'params': {}}).encode('utf-8'),
            headers={'Content-Type': 'application/json'})

    @mute_logger('odoo.http')
    def test_plain_user_is_denied_the_dashboard(self):
        self.authenticate('http_plain', self.plain_password)
        payload = self._call_dashboard().json()
        self.assertIn('error', payload,
                      'مستخدم عادي قرأ غرفة العمليات')

    def test_dispatcher_is_allowed_the_dashboard(self):
        """الضابط المقابل: الفحص لم يُغلق الشاشة على أصحابها."""
        self.authenticate('http_dispatcher', self.dispatcher_password)
        payload = self._call_dashboard().json()
        self.assertNotIn('error', payload)
        self.assertIn('kpis', payload['result'])


@tagged('post_install', '-at_install')
class TestMerchantIntake(HttpCase):
    """المواصفة تأتي من التاجر لا منّا: نلتقط النداء كما وصل، ونكتب
    المُحوّل من الواقع لا من الورق."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['quick.delivery.driver'].sudo().with_context(
            active_test=False).search([]).write({'driver_status': 'offline'})
        cls.client = cls.env['res.partner'].create({
            'name': 'العثيم للاختبار', 'is_qcommerce_client': True,
            'api_key': 'INTAKE-KEY-1'})
        cls.client.action_qd_generate_intake_code()
        cls.code = cls.client.qd_intake_code
        cls.env.cr.flush()

    def _push(self, body, code=None, raw=False, headers=None):
        payload = body if raw else json.dumps(body)
        return self.url_open(
            '/api/v1/intake/%s' % (code or self.code),
            data=payload.encode('utf-8'),
            headers={'Content-Type': 'application/json', **(headers or {})})

    def _native_body(self, order_id='IN-1'):
        return {
            'order_id': order_id,
            'store': {'store_name': 'فرع العليا', 'lat': 24.71, 'lng': 46.67},
            'customer': {'name': 'عميل', 'phone': '0550000000',
                         'lat': 24.72, 'lng': 46.68},
            'payment': {'method': 'PREPAID'},
        }

    # ------------------------------------------------------- المسار
    def test_the_generated_code_is_not_guessable(self):
        self.assertGreaterEqual(len(self.code), 12)
        self.assertIn('-', self.code)

    def test_the_url_is_built_from_the_code(self):
        self.assertTrue(self.client.qd_intake_url.endswith(
            '/api/v1/intake/%s' % self.code))

    def test_an_unknown_code_is_refused(self):
        response = self._push(self._native_body(), code='لا-يوجد')
        self.assertEqual(response.status_code, 404)

    def test_regenerating_the_code_kills_the_old_url(self):
        old = self.code
        self.client.action_qd_generate_intake_code()
        self.env.cr.flush()
        self.assertEqual(self._push(self._native_body('IN-OLD'),
                                    code=old).status_code, 404)

    # --------------------------------------------- وضع الالتقاط
    def test_a_known_format_becomes_an_order(self):
        response = self._push(self._native_body('IN-OK'))
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertTrue(body['tracking_number'])
        record = self.env['quick.delivery.inbox'].browse(body['intake_id'])
        self.assertEqual(record.state, 'mapped')
        self.assertTrue(record.order_id)

    def test_an_unknown_format_is_captured_not_lost(self):
        """جوهر الفكرة: صيغة مجهولة تماماً لا تضيع."""
        response = self._push({'theirOrderNo': 'X-9', 'lat': 24.7})
        self.assertEqual(response.status_code, 202, response.text)
        record = self.env['quick.delivery.inbox'].browse(
            response.json()['intake_id'])
        self.assertEqual(record.state, 'failed')
        self.assertFalse(record.order_id)
        self.assertIn('theirOrderNo', record.raw_body,
                      'الجسم لم يُحفظ كما وصل - لا دليل يوم الربط')

    def test_even_broken_json_is_captured(self):
        response = self._push('{ليس JSON', raw=True)
        self.assertEqual(response.status_code, 202)
        record = self.env['quick.delivery.inbox'].browse(
            response.json()['intake_id'])
        self.assertEqual(record.state, 'failed')
        self.assertIn('ليس JSON', record.raw_body)

    def test_secrets_in_headers_are_masked(self):
        """السجل يقرأه غير واحد: نعرف أي ترويسة استعملوها، لا سرّهم."""
        self._push(self._native_body('IN-HDR'),
                   headers={'X-API-Key': 'SUPER-SECRET-VALUE-123456'})
        record = self.env['quick.delivery.inbox'].search(
            [('client_id', '=', self.client.id)], limit=1)
        stored = json.dumps(record.headers, ensure_ascii=False)
        self.assertNotIn('SUPER-SECRET-VALUE-123456', stored)
        self.assertIn('X-Api-Key', stored)

    def test_replay_turns_a_captured_call_into_an_order(self):
        """ما التُقط قبل كتابة المُحوّل يُعاد تحويله بأثر رجعي."""
        record = self.env['quick.delivery.inbox'].create({
            'client_id': self.client.id,
            'raw_body': json.dumps(self._native_body('IN-REPLAY')),
            'state': 'failed', 'error': 'لا مُحوّل بعد',
        })
        record.action_replay()
        self.assertEqual(record.state, 'mapped')
        self.assertTrue(record.order_id)

    def test_replaying_twice_does_not_duplicate_the_order(self):
        record = self.env['quick.delivery.inbox'].create({
            'client_id': self.client.id,
            'raw_body': json.dumps(self._native_body('IN-TWICE')),
            'state': 'failed',
        })
        record.action_replay()
        first = record.order_id
        record.write({'state': 'failed'})
        record.action_replay()
        self.assertEqual(record.order_id, first,
                         'إعادة المعالجة مرتين أنشأت طلبين')

    # ------------------------------------------- وضع الإنتاج
    def test_strict_mode_refuses_an_unknown_format_with_400(self):
        """بعد الربط: قبول طلب لا نفهمه يعني طلباً لن يصل أحداً."""
        self.client.qd_capture_mode = False
        self.env.cr.flush()
        response = self._push({'theirOrderNo': 'X-10'})
        self.assertEqual(response.status_code, 400)

    def test_strict_mode_still_accepts_a_known_format(self):
        """الضابط المقابل."""
        self.client.qd_capture_mode = False
        self.env.cr.flush()
        response = self._push(self._native_body('IN-STRICT'))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()['tracking_number'])

    def test_strict_mode_is_idempotent(self):
        self.client.qd_capture_mode = False
        self.env.cr.flush()
        first = self._push(self._native_body('IN-IDEM'))
        second = self._push(self._native_body('IN-IDEM'))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['tracking_number'],
                         second.json()['tracking_number'])

    def test_no_traceback_leaks_from_the_intake(self):
        self.client.qd_capture_mode = False
        self.env.cr.flush()
        body = self._push('{', raw=True).text
        for leak in ('Traceback', 'File "', 'quick_delivery/'):
            self.assertNotIn(leak, body)


@tagged('post_install', '-at_install')
class TestCustomerTracking(HttpCase):
    """صفحة العميل النهائي: بها يصله رمز التسليم وحالة طلبه."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['quick.delivery.driver'].sudo().with_context(
            active_test=False).search([]).write({'driver_status': 'offline'})
        cls.driver = cls.env['quick.delivery.driver'].create({
            'name': 'مندوب التتبع', 'phone': '0555550001', 'pin': '1234',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753})
        cls.client = cls.env['res.partner'].create({
            'name': 'سوبرماركت التتبع', 'is_qcommerce_client': True,
            'api_key': 'TRACK-KEY-1'})
        cls.order = cls.env['quick.delivery.order'].create({
            'client_id': cls.client.id, 'merchant_order_id': 'TRK-1',
            'store_name': 'فرع العليا', 'store_lat': 24.71, 'store_lng': 46.67,
            'customer_name': 'عبدالله السرّي', 'customer_phone': '0509998888',
            'customer_lat': 24.72, 'customer_lng': 46.68,
            'address_notes': 'فيلا 23 شارع سرّي',
            'payment_method': 'COD', 'cod_amount': 185.5,
        })
        cls.env.cr.flush()

    def _page(self, token=None):
        return self.url_open('/track/%s' % (token or self.order.tracking_token))

    def _json(self, token=None):
        return self.url_open(
            '/api/v1/track/%s' % (token or self.order.tracking_token))

    # ------------------------------------------------------- الرمز
    def test_every_order_gets_a_long_random_token(self):
        """رقم تتبع متسلسل يُخمَّن، فيُقرأ رمز تسليم أي طلب."""
        self.assertGreaterEqual(len(self.order.tracking_token), 24)
        other = self.env['quick.delivery.order'].create({
            'client_id': self.client.id, 'merchant_order_id': 'TRK-2',
            'store_name': 'فرع', 'store_lat': 24.71, 'store_lng': 46.67,
            'customer_name': 'عميل', 'customer_phone': '0550000000',
            'customer_lat': 24.72, 'customer_lng': 46.68})
        self.assertNotEqual(other.tracking_token, self.order.tracking_token)

    def test_the_url_is_built_from_the_token(self):
        self.assertTrue(self.order.tracking_url.endswith(
            '/track/%s' % self.order.tracking_token))

    # ------------------------------------------------------ الصفحة
    def test_the_page_opens_for_anyone_with_the_link(self):
        response = self._page()
        self.assertEqual(response.status_code, 200)
        self.assertIn('تتبّع طلبك', response.text)

    def test_a_wrong_token_gets_404(self):
        self.assertEqual(self._page('x' * 40).status_code, 404)

    def test_a_short_token_is_refused_without_a_lookup(self):
        self.assertEqual(self._page('123').status_code, 404)

    def test_the_customer_sees_the_delivery_code(self):
        """هذا هو الغرض كله: أن يصل الرمز إلى صاحبه."""
        body = self._page().text
        self.assertIn(self.order.sudo().delivery_otp, body)
        self.assertIn('رمز التسليم', body)

    def test_the_page_leaks_nothing_private(self):
        """من يقع الرابط بيده لا يجوز أن يقرأ اسم العميل وعنوانه."""
        body = self._page().text
        for secret in ('عبدالله السرّي', '0509998888', 'فيلا 23 شارع سرّي',
                       'TRK-1'):
            self.assertNotIn(secret, body,
                             'الصفحة تسرّب: %s' % secret)

    def test_the_cod_amount_is_shown(self):
        self.assertIn('185.50', self._page().text)

    def test_the_code_disappears_after_delivery(self):
        """رابط محفوظ في جوال العميل لا يبقى حاملاً سرّاً بلا سبب."""
        otp = self.order.sudo().delivery_otp
        self.order.write({'driver_id': self.driver.id,
                          'state': 'driver_assigned'})
        self.order.write({'state': 'picked_up'})
        self.order.action_mark_delivered(otp_code=otp)
        self.env.cr.flush()
        body = self._page().text
        self.assertNotIn(otp, body)

    # -------------------------------------------------------- JSON
    def test_the_json_endpoint_feeds_the_live_refresh(self):
        response = self._json()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tracking_number'], self.order.name)
        self.assertTrue(data['is_open'])
        self.assertNotIn('customer_name', data)
        self.assertNotIn('merchant_order_id', data)

    def test_the_json_endpoint_refuses_a_wrong_token(self):
        self.assertEqual(self._json('y' * 40).status_code, 404)

    def test_the_driver_appears_once_assigned(self):
        self.order.write({'driver_id': self.driver.id,
                          'state': 'driver_assigned'})
        self.env.cr.flush()
        data = self._json().json()
        self.assertEqual(data['driver_name'], 'مندوب التتبع')
        self.assertEqual(data['driver_phone'], '0555550001')

    def test_the_merchant_webhook_carries_the_link(self):
        """التاجر يضعه في رسالته لعميله - وبه يصل الرمز إلى صاحبه."""
        payload = self.order._merchant_webhook_payload()
        self.assertIn('/track/', payload['tracking_url'])
        self.assertNotIn('delivery_otp', payload,
                         'الرمز يُنشر في سجلات التاجر بلا داعٍ')


@tagged('post_install', '-at_install')
class TestScopedOperationsRoom(HttpCase):
    """غرفة عمليات لكل سوبرماركت.

    الطلبات تُرشَّح، والمندوبون لا: المندوب مشترك بين العثيم وبندة في
    نفس الوردية، وإخفاء من يعمل لغيرها يُفقد رؤية الطاقة المتاحة -
    وهي نصف فائدة الخريطة، إذ منها يُسنَد يدوياً.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['quick.delivery.driver'].sudo().with_context(
            active_test=False).search([]).write({'driver_status': 'offline'})
        cls.othaim = cls.env['res.partner'].create({
            'name': 'العثيم - غرفة', 'is_qcommerce_client': True,
            'api_key': 'ROOM-KEY-1'})
        cls.panda = cls.env['res.partner'].create({
            'name': 'بندة - غرفة', 'is_qcommerce_client': True,
            'api_key': 'ROOM-KEY-2'})
        cls.driver = cls.env['quick.delivery.driver'].create({
            'name': 'مندوب مشترك', 'phone': '0556660001',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753})
        cls.password = 'roompass123'
        cls.dispatcher = cls.env['res.users'].create({
            'name': 'غرفة عمليات النطاق', 'login': 'room_dispatcher',
            'password': cls.password,
            'group_ids': [(6, 0, [
                cls.env.ref('quick_delivery.group_qd_dispatcher').id])]})
        cls.env.cr.flush()

    def _new_order(self, client, ref, driver=None):
        vals = {
            'client_id': client.id, 'merchant_order_id': ref,
            'store_name': 'فرع', 'store_lat': 24.71, 'store_lng': 46.67,
            'customer_name': 'عميل', 'customer_phone': '0550000000',
            'customer_lat': 24.72, 'customer_lng': 46.68,
        }
        if driver:
            vals.update({'driver_id': driver.id, 'state': 'driver_assigned'})
        order = self.env['quick.delivery.order'].create(vals)
        self.env.cr.flush()
        return order

    def _room(self, client_id=None):
        params = {} if client_id is None else {'client_id': client_id}
        response = self.url_open(
            '/api/v1/qcommerce/dashboard',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                             'params': params}).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        return response.json()

    def setUp(self):
        super().setUp()
        self.authenticate('room_dispatcher', self.password)

    # ------------------------------------------------------------------
    def test_the_global_room_still_shows_everything(self):
        """الضابط: إضافة النطاق لم تكسر العرض العام."""
        self._new_order(self.othaim, 'ROOM-G1')
        self._new_order(self.panda, 'ROOM-G2')
        result = self._room()['result']
        names = {o['client_name'] for o in result['orders']}
        self.assertIn('العثيم - غرفة', names)
        self.assertIn('بندة - غرفة', names)
        self.assertFalse(result['scope']['client_id'])

    def test_a_scoped_room_shows_one_merchant_only(self):
        self._new_order(self.othaim, 'ROOM-S1')
        self._new_order(self.panda, 'ROOM-S2')
        result = self._room(self.othaim.id)['result']
        names = {o['client_name'] for o in result['orders']}
        self.assertEqual(names, {'العثيم - غرفة'})
        self.assertEqual(result['scope']['client_name'], 'العثيم - غرفة')

    def test_the_scoped_kpis_count_that_merchant_only(self):
        self._new_order(self.othaim, 'ROOM-K1')
        self._new_order(self.panda, 'ROOM-K2')
        self._new_order(self.panda, 'ROOM-K3')
        self.assertEqual(self._room(self.othaim.id)['result']
                         ['kpis']['active_count'], 1)
        self.assertEqual(self._room(self.panda.id)['result']
                         ['kpis']['active_count'], 2)

    def test_every_driver_stays_visible_in_a_scoped_room(self):
        """القرار المقصود: الطاقة المتاحة لا تختفي بتضييق النطاق."""
        self._new_order(self.panda, 'ROOM-D1', driver=self.driver)
        drivers = self._room(self.othaim.id)['result']['drivers']
        names = [d['name'] for d in drivers]
        self.assertIn('مندوب مشترك', names,
                      'اختفى المندوب من خريطة شركة أخرى - فلا تُرى الطاقة')

    def test_a_driver_busy_for_another_merchant_is_flagged(self):
        self._new_order(self.panda, 'ROOM-D2', driver=self.driver)
        drivers = {d['name']: d for d
                   in self._room(self.othaim.id)['result']['drivers']}
        entry = drivers['مندوب مشترك']
        self.assertEqual(entry['busy_for'], 'بندة - غرفة')
        self.assertTrue(entry['busy_for_other'])

    def test_the_same_driver_is_not_flagged_inside_his_own_merchant(self):
        """الضابط المقابل: لا يُعلَّم في غرفة الشركة التي يعمل لها."""
        self._new_order(self.panda, 'ROOM-D3', driver=self.driver)
        drivers = {d['name']: d for d
                   in self._room(self.panda.id)['result']['drivers']}
        self.assertFalse(drivers['مندوب مشترك']['busy_for_other'])

    def test_a_free_driver_is_not_flagged(self):
        drivers = {d['name']: d for d
                   in self._room(self.othaim.id)['result']['drivers']}
        self.assertEqual(drivers['مندوب مشترك']['busy_for'], '')
        self.assertFalse(drivers['مندوب مشترك']['busy_for_other'])

    def test_the_scope_carries_the_merchant_list_for_switching(self):
        clients = self._room(self.othaim.id)['result']['scope']['clients']
        names = {c['name'] for c in clients}
        self.assertIn('العثيم - غرفة', names)
        self.assertIn('بندة - غرفة', names)

    @mute_logger('odoo.http')
    def test_an_unknown_merchant_is_refused(self):
        self.assertIn('error', self._room(999999999))

    @mute_logger('odoo.http')
    def test_a_non_merchant_partner_is_refused(self):
        """شريك عادي ليس سوبرماركت: لا يُفتح له نطاق."""
        plain = self.env['res.partner'].create({'name': 'شريك عادي'})
        self.env.cr.flush()
        self.assertIn('error', self._room(plain.id))
