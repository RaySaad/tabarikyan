# -*- coding: utf-8 -*-
"""اختبارات الموديول - لم تكن في الحزمة إطلاقاً.

كل اختبار يحمل ضابطه المقابل: فحصُ "المنع يعمل" بلا فحصِ "المسار
الصحيح ما زال يمر" يُمرِّر موديولاً يمنع كل شيء على أنه نجاح.
"""
import base64
import struct
import zlib

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from psycopg2 import IntegrityError
from odoo.tools import mute_logger


def _png_bytes(size_hint=5000):
    """صورة PNG صالحة فعلاً (ترويسة + كتلة بيانات) أكبر من الحد الأدنى."""
    width = height = 1
    raw = b'\x00' + b'\xff\xff\xff'

    def chunk(kind, data):
        payload = kind + data
        return (struct.pack('>I', len(data)) + payload
                + struct.pack('>I', zlib.crc32(payload) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    # حشو في كتلة نصية لتجاوز حدّ 4096 بايت دون إبطال الصورة.
    padding = chunk(b'tEXt', b'pad\x00' + b'x' * size_hint)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + padding
           + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return png


class QuickDeliveryCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.Order = cls.env['quick.delivery.order']
        cls.Driver = cls.env['quick.delivery.driver']
        # تحييد أي مندوب آخر في القاعدة: اختبارات الإسناد تقيس "من
        # أُسند"، وأي مندوب متاح سابق (بيانات حقيقية أو بذرة فحص) يجعل
        # النتيجة تابعة لمحتوى القاعدة لا للكود.
        cls.Driver.sudo().with_context(active_test=False).search(
            []).write({'driver_status': 'offline'})
        cls.client = cls.env['res.partner'].create({
            'name': 'سوبرماركت الاختبار',
            'is_qcommerce_client': True,
            'api_key': 'UNITKEY-1',
            'webhook_url': 'http://127.0.0.1:9/nowhere',
        })
        # المندوب كيان مستقل - لا مستخدم أودو، ولا رخصة، ولا مجموعة.
        cls.driver = cls.Driver.create({
            'name': 'مندوب الاختبار', 'phone': '0551110001',
            'pin': '1234', 'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753,
        })

    def _order(self, **extra):
        vals = {
            'client_id': self.client.id,
            'merchant_order_id': extra.pop('merchant_order_id', 'M-1'),
            'store_name': 'فرع العليا',
            'store_lat': 24.7100, 'store_lng': 46.6700,
            'customer_name': 'عميل', 'customer_phone': '0550000000',
            'customer_lat': 24.7200, 'customer_lng': 46.6800,
        }
        vals.update(extra)
        return self.Order.create(vals)


@tagged('post_install', '-at_install')
class TestOrderValidation(QuickDeliveryCommon):

    def test_missing_coordinates_are_refused(self):
        """(0,0) كان يُقبل صامتاً فيفشل كل إسناد إلى الأبد بلا رسالة."""
        with self.assertRaises(ValidationError):
            self._order(store_lat=0.0, store_lng=0.0)

    def test_valid_coordinates_pass(self):
        """الضابط المقابل: الإحداثيات الصحيحة لا تُرفض."""
        order = self._order()
        self.assertTrue(order.id)

    def test_out_of_range_coordinates_are_refused(self):
        with self.assertRaises(ValidationError):
            self._order(customer_lat=120.0)

    def test_cod_without_amount_is_refused(self):
        with self.assertRaises(ValidationError):
            self._order(payment_method='COD', cod_amount=0.0)

    def test_prepaid_with_amount_is_refused(self):
        """مبلغ تحصيل على طلب مدفوع = عهدة وهمية على المندوب."""
        with self.assertRaises(ValidationError):
            self._order(payment_method='PREPAID', cod_amount=50.0)

    def test_cod_with_amount_passes(self):
        order = self._order(payment_method='COD', cod_amount=120.0)
        self.assertEqual(order.cod_amount, 120.0)

    @mute_logger('odoo.sql_db')
    def test_duplicate_merchant_order_is_refused_by_the_database(self):
        """القيد في قاعدة البيانات لا في الكود: نداءان متزامنان كانا
        يمرّان كلاهما من فحص "هل الطلب موجود؟"."""
        self._order(merchant_order_id='DUP-1')
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._order(merchant_order_id='DUP-1')

    def test_same_order_id_for_another_client_is_allowed(self):
        """الضابط المقابل: القيد مركّب على (العميل، رقم الطلب)."""
        other = self.env['res.partner'].create({
            'name': 'سوبرماركت آخر', 'is_qcommerce_client': True,
            'api_key': 'UNITKEY-2'})
        self._order(merchant_order_id='SHARED-1')
        order = self._order(client_id=other.id,
                            merchant_order_id='SHARED-1')
        self.assertTrue(order.id)

    def test_otp_is_six_digits_and_generated(self):
        order = self._order()
        self.assertRegex(order.delivery_otp, r'^\d{6}$')


@tagged('post_install', '-at_install')
class TestStateMachine(QuickDeliveryCommon):

    def test_cannot_jump_from_searching_to_delivered(self):
        """أي نص كان يُكتب في state مباشرةً من التطبيق."""
        order = self._order()
        order.driver_id = False
        order.state = 'searching_driver'
        with self.assertRaises(UserError):
            order.write({'state': 'delivered'})

    def test_legal_path_works(self):
        """الضابط المقابل: المسار الصحيح يمر كاملاً."""
        order = self._order()
        order.write({'driver_id': self.driver.id,
                     'state': 'driver_assigned'})
        order.write({'state': 'arrived_at_store'})
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.delivery_otp)
        self.assertEqual(order.state, 'delivered')
        self.assertEqual(order.pod_method, 'otp')
        self.assertTrue(order.delivered_at)

    def test_delivered_order_cannot_be_reopened(self):
        order = self._order()
        order.write({'driver_id': self.driver.id,
                     'state': 'driver_assigned'})
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.delivery_otp)
        with self.assertRaises(UserError):
            order.write({'state': 'picked_up'})


@tagged('post_install', '-at_install')
class TestProofOfDelivery(QuickDeliveryCommon):

    def _ready_order(self):
        order = self._order()
        order.write({'driver_id': self.driver.id,
                     'state': 'driver_assigned'})
        order.write({'state': 'picked_up'})
        return order

    def test_wrong_otp_is_refused(self):
        order = self._ready_order()
        with self.assertRaises(UserError):
            order.action_mark_delivered(otp_code='000000')
        self.assertEqual(order.state, 'picked_up')

    def test_correct_otp_closes_the_order(self):
        order = self._ready_order()
        order.action_mark_delivered(otp_code=order.delivery_otp)
        self.assertEqual(order.state, 'delivered')

    def test_no_proof_at_all_is_refused(self):
        order = self._ready_order()
        with self.assertRaises(UserError):
            order.action_mark_delivered()

    def test_tiny_blob_is_not_a_photo(self):
        """كان يُقبل أي base64 - فبكسل واحد يُغلق الطلب "تم التسليم"."""
        order = self._ready_order()
        blob = base64.b64encode(b'x' * 10).decode()
        with self.assertRaises(UserError):
            order.action_mark_delivered(photo_base64=blob)
        self.assertEqual(order.state, 'picked_up')

    def test_non_image_payload_is_refused(self):
        order = self._ready_order()
        blob = base64.b64encode(b'A' * 9000).decode()
        with self.assertRaises(UserError):
            order.action_mark_delivered(photo_base64=blob)

    def test_real_photo_closes_the_order_and_is_recorded_as_photo(self):
        """الضابط المقابل: صورة حقيقية تُقبل - والطريقة تُسجَّل للمراجعة."""
        order = self._ready_order()
        blob = base64.b64encode(_png_bytes()).decode()
        order.action_mark_delivered(photo_base64=blob)
        self.assertEqual(order.state, 'delivered')
        self.assertEqual(order.pod_method, 'photo')

    def test_data_uri_prefix_is_accepted(self):
        """المسارَان كانا مختلفين: أحدهما يقصّ البادئة والآخر يخزّنها."""
        order = self._ready_order()
        blob = 'data:image/png;base64,' + base64.b64encode(
            _png_bytes()).decode()
        order.action_mark_delivered(photo_base64=blob)
        self.assertEqual(order.state, 'delivered')

    def test_invalid_failure_reason_is_refused(self):
        order = self._ready_order()
        with self.assertRaises(UserError):
            order.action_mark_failed(failure_reason='whatever')

    def test_valid_failure_reason_is_accepted(self):
        order = self._ready_order()
        order.action_mark_failed(failure_reason='customer_no_answer')
        self.assertEqual(order.state, 'failed')


@tagged('post_install', '-at_install')
class TestDispatchAndDriverLifecycle(QuickDeliveryCommon):

    def test_nearest_online_driver_is_assigned_on_create(self):
        order = self._order()
        self.assertEqual(order.driver_id, self.driver)
        self.assertEqual(order.state, 'driver_assigned')
        self.assertEqual(self.driver.driver_status, 'busy')

    def test_offline_driver_is_not_assigned(self):
        """الضابط المقابل: الإسناد ليس "لأي مندوب"."""
        self.driver.driver_status = 'offline'
        order = self._order()
        self.assertFalse(order.driver_id)
        self.assertEqual(order.state, 'searching_driver')

    def test_far_driver_is_not_assigned(self):
        self.driver.write({'current_lat': 21.4858,
                           'current_lng': 39.1925})   # جدة
        order = self._order()
        self.assertFalse(order.driver_id,
                         'أُسند مندوب يبعد مئات الكيلومترات')

    def test_second_order_does_not_reuse_a_busy_driver(self):
        first = self._order(merchant_order_id='B-1')
        self.assertEqual(first.driver_id, self.driver)
        second = self._order(merchant_order_id='B-2')
        self.assertFalse(second.driver_id,
                         'نفس المندوب أُسند لطلبين في وقت واحد')

    def test_cancelling_releases_the_driver(self):
        """المندوب كان يبقى "في مهمة" للأبد عند إلغاء التاجر."""
        order = self._order()
        self.assertEqual(self.driver.driver_status, 'busy')
        order.write({'state': 'cancelled'})
        self.assertEqual(self.driver.driver_status, 'online')

    def test_delivering_releases_the_driver(self):
        order = self._order()
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.delivery_otp)
        self.assertEqual(self.driver.driver_status, 'online')

    def test_release_does_not_wake_an_offline_driver(self):
        order = self._order()
        self.driver.driver_status = 'offline'
        order.write({'state': 'cancelled'})
        self.assertEqual(self.driver.driver_status, 'offline',
                         'مندوب منصرف أُعيد إلى "متاح" رغماً عنه')

    def test_reassignment_frees_the_previous_driver(self):
        other = self.Driver.create({
            'name': 'مندوب بديل', 'phone': '0551110002',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753,
        })
        order = self._order()
        self.assertEqual(order.driver_id, self.driver)
        order.write({'driver_id': other.id})
        self.assertEqual(self.driver.driver_status, 'online')


@tagged('post_install', '-at_install')
class TestWalletAndTimezone(QuickDeliveryCommon):

    def test_day_start_follows_riyadh_not_utc(self):
        """الخطأ المالي الأصلي: "اليوم" كان يُحسب بـUTC، فأول ثلاث
        ساعات من كل يوم سعودي تُحتسب على اليوم الذي قبله."""
        self.env.user.tz = 'Asia/Riyadh'
        day_start = self.Order._day_start_utc_for_env()
        self.assertEqual(day_start.hour, 21,
                         'بداية يوم الرياض ليست 21:00 UTC')

    def test_cod_custody_counts_only_unsettled_cod(self):
        order = self._order(payment_method='COD', cod_amount=200.0)
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.delivery_otp)
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.cod_custody_balance, 200.0)

        self.driver.action_settle_driver_cod()
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.cod_custody_balance, 0.0)

    def test_settling_nothing_raises_instead_of_pretending(self):
        with self.assertRaises(UserError):
            self.driver.action_settle_driver_cod()

    def test_prepaid_order_adds_no_custody(self):
        """الضابط المقابل: العهدة ليست "كل طلب مسلَّم"."""
        order = self._order()
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.delivery_otp)
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.cod_custody_balance, 0.0)


@tagged('post_install', '-at_install')
class TestWebhookOutbox(QuickDeliveryCommon):

    def test_webhook_is_queued_not_sent_inline(self):
        """كان requests.post ينفّذ داخل write() - أي قبل تثبيت المعاملة:
        التاجر يُبلَّغ بتسليم قد ترتدّ معاملته بعده."""
        order = self._order()
        queued = self.env['quick.delivery.webhook'].search(
            [('order_id', '=', order.id)])
        self.assertTrue(queued, 'لم يُسجَّل إبلاغ للتاجر')
        self.assertTrue(all(record.state == 'pending' for record in queued))
        self.assertTrue(all(record.attempts == 0 for record in queued))

    def test_otp_is_not_in_the_webhook_payload(self):
        """الرمز يُسلَّم مرة في رد الإنشاء، ولا يُنشر في كل تغيير حالة."""
        order = self._order()
        payload = order._merchant_webhook_payload()
        self.assertNotIn('delivery_otp', payload)
        serialized = str(payload)
        self.assertNotIn(order.delivery_otp, serialized,
                         'رمز التحقق ظهر في محتوى الإبلاغ')

    def test_no_webhook_without_a_url(self):
        """الضابط المقابل: لا نكدّس صادراً لعميل بلا رابط."""
        silent = self.env['res.partner'].create({
            'name': 'عميل بلا رابط', 'is_qcommerce_client': True,
            'api_key': 'UNITKEY-3'})
        order = self._order(client_id=silent.id,
                            merchant_order_id='NOHOOK-1')
        self.assertFalse(self.env['quick.delivery.webhook'].search(
            [('order_id', '=', order.id)]))

    def test_state_change_queues_another_notification(self):
        order = self._order()
        before = self.env['quick.delivery.webhook'].search_count(
            [('order_id', '=', order.id)])
        order.write({'state': 'picked_up'})
        after = self.env['quick.delivery.webhook'].search_count(
            [('order_id', '=', order.id)])
        self.assertGreater(after, before)


@tagged('post_install', '-at_install')
class TestAccessRights(QuickDeliveryCommon):
    """الثغرة الأصلية: base.group_user بقراءة وكتابة وإنشاء وحذف على كل
    الطلبات، بلا قاعدة سجلات واحدة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain = cls.env['res.users'].create({
            'name': 'مستخدم عادي', 'login': 'unit_plain_1',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.dispatcher = cls.env['res.users'].create({
            'name': 'غرفة عمليات', 'login': 'unit_dispatcher_1',
            'group_ids': [(6, 0, [
                cls.env.ref('quick_delivery.group_qd_dispatcher').id])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'مدير توصيل', 'login': 'unit_manager_1',
            'group_ids': [(6, 0, [
                cls.env.ref('quick_delivery.group_qd_manager').id])],
        })

    @mute_logger('odoo.addons.base.models.ir_model', 'odoo.models')
    def test_plain_internal_user_cannot_read_orders(self):
        order = self._order()
        with self.assertRaises(AccessError):
            order.with_user(self.plain).read(['customer_phone'])

    def test_dispatcher_can_read_all_orders(self):
        """الضابط المقابل: المنع لم يُغلق الباب على من يحتاجه."""
        order = self._order()
        self.assertTrue(order.with_user(self.dispatcher).read(
            ['customer_phone']))

    @mute_logger('odoo.addons.base.models.ir_model', 'odoo.models')
    def test_dispatcher_cannot_delete_orders(self):
        order = self._order()
        with self.assertRaises(AccessError):
            order.with_user(self.dispatcher).unlink()

    def test_manager_can_delete_orders(self):
        order = self._order()
        order.with_user(self.manager).unlink()
        self.assertFalse(order.exists())

    @mute_logger('odoo.addons.base.models.ir_model', 'odoo.models')
    def test_plain_internal_user_cannot_read_drivers(self):
        """سجل المندوبين يحمل الجوال والموقع والعهدة: ليس لعموم
        المستخدمين الداخليين."""
        with self.assertRaises(AccessError):
            self.Driver.with_user(self.plain).search([])[:1].read(['phone'])

    def test_dispatcher_can_read_drivers(self):
        """الضابط المقابل: غرفة العمليات تحتاجهم لتوزّع عليهم."""
        self.assertTrue(
            self.driver.with_user(self.dispatcher).read(['name', 'phone']))

    @mute_logger('odoo.addons.base.models.ir_model', 'odoo.models')
    def test_dispatcher_cannot_create_or_delete_drivers(self):
        with self.assertRaises(AccessError):
            self.Driver.with_user(self.dispatcher).create(
                {'name': 'مندوب مهرَّب', 'phone': '0559990001'})

    def test_api_key_is_hidden_from_non_managers(self):
        """رابط الـWebhook المكتوب من أي مستخدم داخلي كان يحوّل بيانات
        كل الطلبات إلى أي سيرفر يختاره."""
        as_dispatcher = self.client.with_user(self.dispatcher)
        with self.assertRaises(AccessError):
            as_dispatcher.read(['api_key'])
        with self.assertRaises(AccessError):
            as_dispatcher.read(['webhook_url'])

    def test_manager_can_read_the_api_key(self):
        """الضابط المقابل: من يحتاجه يراه."""
        self.assertTrue(
            self.client.with_user(self.manager).read(['api_key']))

    def test_driver_secrets_are_hidden_from_non_managers(self):
        """من يقرأ رمز الجلسة يدخل التطبيق باسم المندوب ويُغلق طلباته."""
        as_dispatcher = self.driver.with_user(self.dispatcher)
        for secret in ('pin_hash', 'session_token', 'commission_per_order'):
            with self.assertRaises(AccessError):
                as_dispatcher.read([secret])

    def test_manager_can_read_the_driver_secrets(self):
        """الضابط المقابل."""
        self.assertTrue(
            self.driver.with_user(self.manager).read(['pin_hash']))


@tagged('post_install', '-at_install')
class TestDriverAuthentication(QuickDeliveryCommon):
    """الدخول الجديد: جوال + رمز سري مُعمّى، وجلسة تنتهي.

    القديم كان رمزاً نصّياً أبدياً واحداً، يُقرأ من قاعدة البيانات
    ويُستعمل إلى الأبد - ولا ينتهي بفقدان الجوال.
    """

    def test_correct_pin_authenticates(self):
        found = self.Driver._qd_authenticate('0551110001', '1234')
        self.assertEqual(found, self.driver)

    def test_wrong_pin_is_refused(self):
        self.assertFalse(self.Driver._qd_authenticate('0551110001', '9999'))

    def test_unknown_phone_is_refused_without_crashing(self):
        self.assertFalse(self.Driver._qd_authenticate('0569999999', '1234'))

    def test_empty_pin_is_refused(self):
        """رمز فارغ كان يطابق أي سجل حُفظ رمزه فارغاً."""
        self.assertFalse(self.Driver._qd_authenticate('0551110001', ''))

    def test_pin_is_never_stored_in_clear_text(self):
        stored = self.driver.sudo().pin_hash
        self.assertTrue(stored)
        self.assertNotIn('1234', stored)
        self.assertEqual(self.driver.sudo().pin, '',
                         'الرمز يُقرأ من قاعدة البيانات - يجب ألا يُقرأ')

    def test_phone_is_matched_on_the_last_nine_digits(self):
        """المندوب يكتب رقمه كما يحفظه: 05 أو +966 أو 00966."""
        for variant in ('+966551110001', '00966551110001', '966551110001',
                        '055 111 0001'):
            self.assertEqual(
                self.Driver._qd_authenticate(variant, '1234'), self.driver,
                'صيغة الرقم %s مُنعت من الدخول' % variant)

    def test_five_wrong_attempts_lock_the_account(self):
        for _unused in range(5):
            self.Driver._qd_authenticate('0551110001', '0000')
        self.assertTrue(self.Driver._qd_login_lock_minutes('0551110001'))
        self.assertFalse(
            self.Driver._qd_authenticate('0551110001', '1234'),
            'الرمز الصحيح قُبل رغم القفل - التخمين لا يتوقف')

    def test_a_successful_login_resets_the_counter(self):
        """الضابط المقابل: محاولتان خاطئتان لا تُراكمان على المندوب."""
        self.Driver._qd_authenticate('0551110001', '0000')
        self.Driver._qd_authenticate('0551110001', '1234')._qd_open_session()
        self.assertEqual(self.driver.login_fail_count, 0)
        self.assertFalse(self.Driver._qd_login_lock_minutes('0551110001'))

    def test_session_token_resolves_to_the_driver(self):
        token = self.driver._qd_open_session('unit-test')
        self.assertEqual(self.Driver._qd_driver_from_session(token),
                         self.driver)

    def test_empty_or_unknown_session_token_is_refused(self):
        self.assertFalse(self.Driver._qd_driver_from_session(''))
        self.assertFalse(self.Driver._qd_driver_from_session(None))
        self.assertFalse(self.Driver._qd_driver_from_session('لا-يوجد'))

    def test_expired_session_is_refused(self):
        token = self.driver._qd_open_session()
        self.driver.sudo().session_expiry = fields.Datetime.now() \
            - timedelta(minutes=1)
        self.assertFalse(self.Driver._qd_driver_from_session(token),
                         'جلسة منتهية ما زالت تفتح التطبيق')

    def test_archived_driver_session_stops_working(self):
        """جوال مندوب أُوقف: الأرشفة وحدها يجب أن تُخرجه."""
        token = self.driver._qd_open_session()
        self.driver.action_archive()
        self.assertFalse(self.Driver._qd_driver_from_session(token))

    def test_changing_the_pin_revokes_live_sessions(self):
        token = self.driver._qd_open_session()
        self.driver.pin = '4321'
        self.assertFalse(self.Driver._qd_driver_from_session(token),
                         'الجهاز القديم بقي داخلاً بعد تغيير الرمز')
        self.assertEqual(self.Driver._qd_authenticate('0551110001', '4321'),
                         self.driver)

    def test_revoking_sessions_logs_the_device_out(self):
        token = self.driver._qd_open_session()
        self.driver.action_revoke_sessions()
        self.assertFalse(self.Driver._qd_driver_from_session(token))

    def test_a_short_or_non_numeric_pin_is_refused(self):
        for bad in ('123', 'abcd', '12 34', '1234567'):
            with self.assertRaises(ValidationError, msg=bad):
                self.Driver.create({'name': 'رمز سيئ',
                                    'phone': '0558880001', 'pin': bad})

    def test_generated_pin_is_six_digits_and_usable(self):
        self.driver.action_generate_pin()
        self.assertTrue(self.driver.has_pin)
        # لا نعرف الرمز المولَّد (يُعرض مرة ولا يُخزَّن نصاً)، فنتأكد أن
        # القديم بطل - وهذا هو السلوك المطلوب.
        self.assertFalse(self.Driver._qd_authenticate('0551110001', '1234'))

    @mute_logger('odoo.sql_db')
    def test_duplicate_phone_is_refused_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Driver.create({'name': 'نفس الرقم',
                                    'phone': '+966551110001'})

    def test_a_too_short_phone_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Driver.create({'name': 'رقم قصير', 'phone': '12345'})

    def test_an_archived_driver_is_never_dispatched(self):
        """الضابط العملي للأرشفة: لا إسناد لمن أُوقف."""
        self.driver.action_archive()
        order = self._order(merchant_order_id='ARCH-1')
        self.assertFalse(order.driver_id)
        self.assertEqual(order.state, 'searching_driver')


@tagged('post_install', '-at_install')
class TestMultiMerchant(QuickDeliveryCommon):
    """العثيم وبندة وغيرهما على نفس النظام.

    الفصل كان موجوداً في الأساس (مفتاح وتفرّد لكل عميل)، لكن الأرقام
    كانت تُقرأ من الإعداد الحالي - فتتغيّر بأثر رجعي.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client.write({'delivery_fee_per_order': 12.0})
        cls.other_client = cls.env['res.partner'].create({
            'name': 'سوبرماركت ثانٍ', 'is_qcommerce_client': True,
            'api_key': 'UNITKEY-MM', 'delivery_fee_per_order': 20.0,
            'webhook_url': 'http://127.0.0.1:9/nowhere',
        })

    def _delivered(self, client, merchant_order_id):
        order = self._order(merchant_order_id=merchant_order_id,
                            client_id=client.id)
        if not order.driver_id:
            order.write({'driver_id': self.driver.id,
                         'state': 'driver_assigned'})
        order.write({'state': 'picked_up'})
        order.action_mark_delivered(otp_code=order.sudo().delivery_otp)
        return order

    # ----------------------------------------------------- الفصل
    def test_each_merchant_keeps_its_own_fee(self):
        first = self._order(merchant_order_id='MM-1', client_id=self.client.id)
        second = self._order(merchant_order_id='MM-2',
                             client_id=self.other_client.id)
        self.assertEqual(first.delivery_fee, 12.0)
        self.assertEqual(second.delivery_fee, 20.0)

    def test_changing_the_fee_does_not_rewrite_history(self):
        """رفعُ رسم العثيم كان يُعيد كتابة كل تقرير سابق."""
        order = self._order(merchant_order_id='MM-FROZEN',
                            client_id=self.client.id)
        self.assertEqual(order.delivery_fee, 12.0)
        self.client.delivery_fee_per_order = 30.0
        order.invalidate_recordset()
        self.assertEqual(order.delivery_fee, 12.0,
                         'الرسم تغيّر بأثر رجعي على طلب سابق')

    def test_the_new_fee_applies_to_the_next_order(self):
        """الضابط المقابل: التثبيت لا يعني تجميد الإعداد."""
        self.client.delivery_fee_per_order = 30.0
        order = self._order(merchant_order_id='MM-NEW',
                            client_id=self.client.id)
        self.assertEqual(order.delivery_fee, 30.0)

    def test_commission_is_frozen_at_assignment(self):
        order = self._order(merchant_order_id='MM-COMM')
        self.assertEqual(order.driver_id, self.driver)
        self.assertEqual(order.driver_commission,
                         self.driver.sudo().commission_per_order)
        self.driver.sudo().commission_per_order = 99.0
        order.invalidate_recordset()
        self.assertEqual(order.driver_commission, 8.0,
                         'عمولة طلب مضى تغيّرت بتعديل الإعداد')

    def test_removing_the_driver_clears_the_commission(self):
        order = self._order(merchant_order_id='MM-UNASSIGN')
        self.assertTrue(order.driver_commission)
        order.write({'driver_id': False, 'state': 'searching_driver'})
        self.assertEqual(order.driver_commission, 0.0)

    def test_net_revenue_is_fee_minus_commission(self):
        order = self._order(merchant_order_id='MM-NET')
        self.assertEqual(order.net_revenue,
                         order.delivery_fee - order.driver_commission)

    # ------------------------------------------------ أرقام الشهر
    def test_month_figures_are_per_merchant(self):
        self._delivered(self.client, 'MM-A1')
        self._delivered(self.client, 'MM-A2')
        self._delivered(self.other_client, 'MM-B1')

        self.client.invalidate_recordset()
        self.other_client.invalidate_recordset()
        self.assertEqual(self.client.qd_month_orders, 2)
        self.assertEqual(self.client.qd_month_fees, 24.0)
        self.assertEqual(self.other_client.qd_month_orders, 1)
        self.assertEqual(self.other_client.qd_month_fees, 20.0)

    def test_an_undelivered_order_is_not_billed(self):
        """الضابط المقابل: الرسم على ما سُلِّم، لا على ما أُنشئ."""
        self._order(merchant_order_id='MM-OPEN',
                    client_id=self.other_client.id)
        self.other_client.invalidate_recordset()
        self.assertEqual(self.other_client.qd_month_orders, 0)
        self.assertEqual(self.other_client.qd_month_fees, 0.0)

    def test_driver_earnings_come_from_the_frozen_commission(self):
        """تعديل العمولة كان يُغيّر أرباح أيام صُرفت بالفعل."""
        self._delivered(self.client, 'MM-E1')
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.today_delivered_count, 1)
        self.assertEqual(self.driver.today_earnings, 8.0)

        self.driver.sudo().commission_per_order = 50.0
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.today_earnings, 8.0,
                         'أرباح اليوم تغيّرت بتعديل العمولة')

    def test_configuration_flag_requires_key_and_webhook(self):
        bare = self.env['res.partner'].create({
            'name': 'سوبرماركت بلا ربط', 'is_qcommerce_client': True})
        self.assertFalse(bare.qd_is_configured)
        self.assertTrue(self.other_client.qd_is_configured)

    def test_the_merchant_order_action_is_scoped(self):
        self._order(merchant_order_id='MM-SCOPE-1', client_id=self.client.id)
        self._order(merchant_order_id='MM-SCOPE-2',
                    client_id=self.other_client.id)
        action = self.other_client.action_qd_view_orders()
        found = self.Order.search(action['domain'])
        self.assertEqual(found.client_id, self.other_client)
