# -*- coding: utf-8 -*-
"""اختبارات دفع الإشعارات.

أهمّها الأول: مطابقة الاشتقاق للمتجه المرجعي في RFC 8291 §5. تشفيرٌ
"يعمل" في اختبار ذهاب-وإياب مع نفسه قد يكون مخالفاً للمواصفة في كل
خطوة ويبقى متّسقاً - ولا يكتشفه أحد إلا جوال المندوب حين لا يصله
شيء. المتجه المرجعي وحده يُثبت أننا نتكلّم لغة المتصفح.
"""
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.quick_delivery.models import webpush
from .test_quick_delivery import QuickDeliveryCommon


# ---------------------------------------------------------------- RFC 8291 §5
RFC_PLAINTEXT = b'When I grow up, I want to be a watermelon'
RFC_UA_PUBLIC = ('BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvT'
                 'BHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4')
RFC_AUTH = 'BTBZMqHH6r4Tts7J_aSIgg'
RFC_SALT = 'DGv6ra1nlYgDCS1FRnbzlw'
RFC_AS_PRIVATE = 'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'
RFC_AS_PUBLIC = ('BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLoc'
                 'InmYWAmS6TlzAC8wEqKK6PBru3jl7A8')
RFC_ECDH_SECRET = 'kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs'
RFC_PRK_KEY = 'Snr3JMxaHVDXHWJn5wdC52WjpCtd2EIEGBykDcZW32k'
RFC_IKM = 'S4lYMb_L0FxCeq0WhDx813KgSYqU26kOyzWUdsXYyrg'
RFC_PRK = '09_eUZGrsvxChDCGRCdkLiDXrReGOEVeSCdCcPBSJSc'
RFC_CEK = 'oIhVW04MRdy2XN9CiKLxTg'
RFC_NONCE = '4h_95klXJ5E_qnoN'


@tagged('post_install', '-at_install')
class TestWebPushCrypto(QuickDeliveryCommon):
    """اشتقاق المفاتيح - بلا قاعدة بيانات، على المتجه المرجعي."""

    def test_the_reference_vector_derivations_match(self):
        """كل خطوة في RFC 8291 §3.4 تُطابق قيمتها المنشورة."""
        import hashlib
        import hmac

        ua_public = webpush.b64d(RFC_UA_PUBLIC)
        as_public = webpush.b64d(RFC_AS_PUBLIC)
        auth = webpush.b64d(RFC_AUTH)
        salt = webpush.b64d(RFC_SALT)

        as_private = webpush.load_private_key(RFC_AS_PRIVATE)
        ua_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), ua_public)
        ecdh_secret = as_private.exchange(ec.ECDH(), ua_key)
        self.assertEqual(webpush.b64e(ecdh_secret), RFC_ECDH_SECRET,
                         'سرّ ECDH لا يطابق المرجع')

        # المفتاح العام المشتقّ من الخاص يطابق المنشور - وإلا كان
        # load_private_key يقرأ صيغةً أخرى.
        from cryptography.hazmat.primitives import serialization
        derived_public = as_private.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        self.assertEqual(webpush.b64e(derived_public), RFC_AS_PUBLIC)

        prk_key = hmac.new(auth, ecdh_secret, hashlib.sha256).digest()
        self.assertEqual(webpush.b64e(prk_key), RFC_PRK_KEY)

        key_info = b'WebPush: info\x00' + ua_public + as_public
        ikm = webpush._hkdf(auth, ecdh_secret, key_info, 32)
        self.assertEqual(webpush.b64e(ikm), RFC_IKM, 'IKM لا يطابق المرجع')

        prk = hmac.new(salt, ikm, hashlib.sha256).digest()
        self.assertEqual(webpush.b64e(prk), RFC_PRK)

        cek = webpush._hkdf(salt, ikm,
                            b'Content-Encoding: aes128gcm\x00', 16)
        self.assertEqual(webpush.b64e(cek), RFC_CEK, 'CEK لا يطابق المرجع')

        nonce = webpush._hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
        self.assertEqual(webpush.b64e(nonce), RFC_NONCE,
                         'NONCE لا يطابق المرجع')

    def test_the_encoded_body_has_the_aes128gcm_header(self):
        """الترويسة: ملح ١٦ + حجم السجل ٤ + طول المفتاح ١ + المفتاح ٦٥."""
        body = webpush.encrypt_payload(
            RFC_PLAINTEXT, RFC_UA_PUBLIC, RFC_AUTH,
            _salt=webpush.b64d(RFC_SALT),
            _as_private=webpush.load_private_key(RFC_AS_PRIVATE))
        self.assertEqual(body[:16], webpush.b64d(RFC_SALT))
        self.assertEqual(int.from_bytes(body[16:20], 'big'), 4096)
        self.assertEqual(body[20], 65)
        self.assertEqual(webpush.b64e(body[21:86]), RFC_AS_PUBLIC)
        # النصّ المشفَّر = النص + فاصل الحشو 0x02 + ١٦ بايت وسم GCM
        self.assertEqual(len(body), 86 + len(RFC_PLAINTEXT) + 1 + 16)

    def test_the_receiver_can_decrypt_what_we_send(self):
        """ذهابٌ وإياب بمفتاح جهازٍ حقيقي - هذا ما يفعله المتصفح."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        ua_private = ec.generate_private_key(ec.SECP256R1())
        ua_public = ua_private.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        auth = b'0123456789abcdef'

        message = 'طلب توصيل جديد'.encode('utf-8')
        body = webpush.encrypt_payload(
            message, webpush.b64e(ua_public), webpush.b64e(auth))

        salt, as_public = body[:16], body[21:86]
        as_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), as_public)
        ecdh = ua_private.exchange(ec.ECDH(), as_key)
        key_info = b'WebPush: info\x00' + ua_public + as_public
        ikm = webpush._hkdf(auth, ecdh, key_info, 32)
        cek = webpush._hkdf(salt, ikm,
                            b'Content-Encoding: aes128gcm\x00', 16)
        nonce = webpush._hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
        plain = AESGCM(cek).decrypt(nonce, body[86:], None)
        self.assertEqual(plain, message + b'\x02')

    def test_each_message_gets_a_fresh_salt(self):
        """إعادة استعمال الملح مع نفس المفتاح كسرٌ كامل لـGCM."""
        first = webpush.encrypt_payload(b'x', RFC_UA_PUBLIC, RFC_AUTH)
        second = webpush.encrypt_payload(b'x', RFC_UA_PUBLIC, RFC_AUTH)
        self.assertNotEqual(first[:16], second[:16])
        self.assertNotEqual(first[21:86], second[21:86],
                            'المفتاح المؤقّت يجب أن يتجدّد أيضاً')

    def test_an_oversized_payload_is_refused(self):
        with self.assertRaises(ValueError):
            webpush.encrypt_payload(b'x' * 9000, RFC_UA_PUBLIC, RFC_AUTH)


@tagged('post_install', '-at_install')
class TestWebPushKeys(QuickDeliveryCommon):

    def test_the_keypair_is_generated_once_and_kept(self):
        Config = self.env['quick.delivery.push.config']
        first = Config._vapid_keys()
        self.assertTrue(all(first))
        self.assertEqual(Config._vapid_keys(), first,
                         'المفتاح يتبدّل في كل نداء - الأجهزة المشتركة تسقط')

    def test_the_public_key_is_an_uncompressed_point(self):
        public = webpush.b64d(
            self.env['quick.delivery.push.config']._vapid_public())
        self.assertEqual(len(public), 65)
        self.assertEqual(public[0], 0x04)

    def test_the_vapid_subject_is_not_a_personal_email(self):
        """المُعرَّف يذهب إلى طرف ثالث - فليكن رابط المثيل لا بريد أحد."""
        subject = self.env['quick.delivery.push.config']._vapid_subject()
        self.assertTrue(subject.startswith('https://')
                        or subject.startswith('mailto:'))

    def test_the_authorization_header_is_a_vapid_token(self):
        Config = self.env['quick.delivery.push.config']
        private, public = Config._vapid_keys()
        headers = webpush.vapid_headers(
            'https://fcm.googleapis.com/fcm/send/abc', private, public,
            'https://example.com')
        self.assertTrue(headers['Authorization'].startswith('vapid t='))
        self.assertIn('k=%s' % public, headers['Authorization'])

        import jwt as pyjwt
        token = headers['Authorization'].split('t=')[1].split(',')[0]
        claims = pyjwt.decode(token, webpush.load_private_key(private
                                                              ).public_key(),
                              algorithms=['ES256'],
                              audience='https://fcm.googleapis.com')
        self.assertEqual(claims['aud'], 'https://fcm.googleapis.com')
        self.assertEqual(claims['sub'], 'https://example.com')


@tagged('post_install', '-at_install')
class TestPushSubscription(QuickDeliveryCommon):

    def setUp(self):
        super().setUp()
        self.Sub = self.env['quick.delivery.push.subscription']
        self.endpoint = 'https://push.example.invalid/sub/one'

    def _register(self, driver=None, endpoint=None):
        return self.Sub._register_device(
            driver or self.driver, endpoint or self.endpoint,
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvT'
            'BHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg', 'Android/Chrome')

    def test_registering_a_device(self):
        device = self._register()
        self.assertEqual(device.driver_id, self.driver)
        self.assertTrue(device.active)

    def test_registering_twice_updates_and_does_not_duplicate(self):
        first = self._register()
        again = self._register()
        self.assertEqual(first, again)
        self.assertEqual(self.Sub.search_count(
            [('endpoint', '=', self.endpoint)]), 1)

    def test_a_handed_over_phone_follows_its_new_driver(self):
        """الجوال يُسلَّم لمندوب آخر - وإلا وصلته طلبات زميله."""
        other = self.env['quick.delivery.driver'].create(
            {'name': 'مندوب ثانٍ', 'phone': '0555000111'})
        self._register()
        self._register(driver=other)
        device = self.Sub.search([('endpoint', '=', self.endpoint)])
        self.assertEqual(len(device), 1)
        self.assertEqual(device.driver_id, other)

    def test_an_internal_endpoint_is_refused(self):
        """نقطة الدفع يكتبها المتصفح - وجوالٌ مُخترَق قد يكتب عنواناً
        داخلياً فيجعل الخادم بوّابةً إلى شبكته."""
        from odoo.addons.quick_delivery.models.outbound_url import (
            OutboundUrlError)
        with self.assertRaises(OutboundUrlError):
            self._register(endpoint='http://169.254.169.254/latest/meta-data')

    def test_incomplete_subscription_data_is_refused(self):
        with self.assertRaises(UserError):
            self.Sub._register_device(self.driver, self.endpoint, '', 'auth')

    def test_a_dead_endpoint_is_disabled_not_deleted(self):
        """الحذف يُضيّع أثر "لماذا لم يصل الإشعار"."""
        device = self._register()
        device._disable('410')
        self.assertFalse(device.active)
        self.assertEqual(self.Sub.with_context(active_test=False).search_count(
            [('endpoint', '=', self.endpoint)]), 1)


class _Response:
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text


@tagged('post_install', '-at_install')
class TestPushOutbox(QuickDeliveryCommon):

    def setUp(self):
        super().setUp()
        self.Push = self.env['quick.delivery.push']
        self.device = self.env['quick.delivery.push.subscription']._register_device(
            self.driver, 'https://push.example.invalid/sub/one',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvT'
            'BHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg', 'Android/Chrome')

    def _message(self, **extra):
        values = {'driver_id': self.driver.id, 'title': 'عنوان',
                  'body': 'نص', 'kind': 'test'}
        values.update(extra)
        return self.Push.create(values)

    def test_a_successful_send_is_recorded(self):
        record = self._message()
        with patch.object(webpush.requests, 'post',
                          return_value=_Response(201)) as sender:
            record._deliver()
        self.assertEqual(record.state, 'sent')
        self.assertEqual(record.device_count, 1)
        self.assertTrue(record.sent_at)
        headers = sender.call_args.kwargs['headers']
        self.assertEqual(headers['Content-Encoding'], 'aes128gcm')
        self.assertTrue(headers['Authorization'].startswith('vapid t='))

    def test_a_driver_without_a_device_is_named_not_silent(self):
        other = self.env['quick.delivery.driver'].create(
            {'name': 'بلا جهاز', 'phone': '0555222333'})
        record = self._message(driver_id=other.id)
        record._deliver()
        self.assertEqual(record.state, 'no_device')
        self.assertIn('الإشعارات', record.last_error)

    def test_a_gone_endpoint_disables_the_device(self):
        record = self._message()
        with patch.object(webpush.requests, 'post',
                          return_value=_Response(410)):
            record._deliver()
        self.assertFalse(self.device.active)
        self.assertEqual(record.state, 'pending',
                         'أول إخفاق لا يُنهي الرسالة - المجدول يعيد')

    def test_failures_back_off_and_eventually_stop(self):
        record = self._message()
        with patch.object(webpush.requests, 'post',
                          return_value=_Response(500, 'boom')):
            for _unused in range(webpush.MAX_ATTEMPTS):
                record.write({'next_attempt_at': False})
                record._deliver()
        self.assertEqual(record.state, 'failed')
        self.assertEqual(record.attempts, webpush.MAX_ATTEMPTS)
        self.assertIn('500', record.last_error)

    def test_a_network_error_is_not_a_dead_device(self):
        record = self._message()
        with patch.object(webpush.requests, 'post',
                          side_effect=webpush.requests.ConnectionError('x')):
            record._deliver()
        self.assertTrue(self.device.active,
                        'انقطاع شبكة الخادم ليس إلغاءً من الجهاز')
        self.assertEqual(record.state, 'pending')

    def test_the_cron_only_takes_due_messages(self):
        record = self._message()
        record.write({'next_attempt_at': '2999-01-01 00:00:00'})
        with patch.object(webpush.requests, 'post',
                          return_value=_Response(201)):
            self.Push.cron_flush_pending()
        self.assertEqual(record.state, 'pending')


@tagged('post_install', '-at_install')
class TestPushOnAssignment(QuickDeliveryCommon):

    def setUp(self):
        super().setUp()
        self.env['quick.delivery.push.subscription']._register_device(
            self.driver, 'https://push.example.invalid/sub/assign',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvT'
            'BHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg', 'Android/Chrome')

    def test_an_assignment_queues_one_notification(self):
        order = self._order(merchant_order_id='PUSH-1')
        self.assertEqual(order.driver_id, self.driver)
        pushes = self.env['quick.delivery.push'].search(
            [('order_id', '=', order.id)])
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes.driver_id, self.driver)

    def test_the_notification_carries_no_customer_details(self):
        """شاشةٌ مقفلة في جهاز يُسلَّم لمندوب آخر غداً."""
        order = self._order(merchant_order_id='PUSH-2')
        push = self.env['quick.delivery.push'].search(
            [('order_id', '=', order.id)])
        text = '%s %s' % (push.title, push.body)
        self.assertNotIn(order.customer_name, text)
        self.assertNotIn(order.customer_phone, text)
        self.assertNotIn(order.sudo().delivery_otp, text)
        self.assertIn(order.store_name, text)

    def test_the_same_order_is_not_notified_twice(self):
        order = self._order(merchant_order_id='PUSH-3')
        order._queue_driver_push()
        order._queue_driver_push()
        self.assertEqual(self.env['quick.delivery.push'].search_count(
            [('order_id', '=', order.id)]), 1)

    def test_the_assignment_time_is_stamped(self):
        order = self._order(merchant_order_id='PUSH-4')
        self.assertTrue(order.assigned_at)
        self.assertFalse(order.driver_seen_at)
        self.assertEqual(order.notify_seconds, 0)

    def test_the_seen_time_is_written_once(self):
        """هذا الرقم هو ما يقرّر لاحقاً: أنحتاج تطبيقاً أصلياً أم لا؟"""
        order = self._order(merchant_order_id='PUSH-5')
        order._mark_seen_by_driver()
        first = order.driver_seen_at
        self.assertTrue(first)
        order._mark_seen_by_driver()
        self.assertEqual(order.driver_seen_at, first,
                         'كل استطلاع كل ثماني ثوان كان سيُعيد ضبط القياس')
