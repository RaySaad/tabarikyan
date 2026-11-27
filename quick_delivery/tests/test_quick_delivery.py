# -*- coding: utf-8 -*-
"""اختبارات الموديول - لم تكن في الحزمة إطلاقاً.

كل اختبار يحمل ضابطه المقابل: فحصُ "المنع يعمل" بلا فحصِ "المسار
الصحيح ما زال يمر" يُمرِّر موديولاً يمنع كل شيء على أنه نجاح.
"""
import base64
import json
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
            'webhook_url': 'http://merchant.invalid/hook',
        })
        # المندوب كيان مستقل - لا مستخدم أودو، ولا رخصة، ولا مجموعة.
        cls.driver = cls.Driver.create({
            'name': 'مندوب الاختبار', 'phone': '0551110001',
            'pin': '7391', 'driver_status': 'online',
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
        found = self.Driver._qd_authenticate('0551110001', '7391')
        self.assertEqual(found, self.driver)

    def test_wrong_pin_is_refused(self):
        self.assertFalse(self.Driver._qd_authenticate('0551110001', '9999'))

    def test_unknown_phone_is_refused_without_crashing(self):
        self.assertFalse(self.Driver._qd_authenticate('0569999999', '7391'))

    def test_empty_pin_is_refused(self):
        """رمز فارغ كان يطابق أي سجل حُفظ رمزه فارغاً."""
        self.assertFalse(self.Driver._qd_authenticate('0551110001', ''))

    def test_pin_is_never_stored_in_clear_text(self):
        stored = self.driver.sudo().pin_hash
        self.assertTrue(stored)
        self.assertNotIn('7391', stored)
        self.assertEqual(self.driver.sudo().pin, '',
                         'الرمز يُقرأ من قاعدة البيانات - يجب ألا يُقرأ')

    def test_phone_is_matched_on_the_last_nine_digits(self):
        """المندوب يكتب رقمه كما يحفظه: 05 أو +966 أو 00966."""
        for variant in ('+966551110001', '00966551110001', '966551110001',
                        '055 111 0001'):
            self.assertEqual(
                self.Driver._qd_authenticate(variant, '7391'), self.driver,
                'صيغة الرقم %s مُنعت من الدخول' % variant)

    def test_five_wrong_attempts_lock_the_account(self):
        for _unused in range(5):
            self.Driver._qd_authenticate('0551110001', '0000')
        self.assertTrue(self.Driver._qd_login_lock_minutes('0551110001'))
        self.assertFalse(
            self.Driver._qd_authenticate('0551110001', '7391'),
            'الرمز الصحيح قُبل رغم القفل - التخمين لا يتوقف')

    def test_a_successful_login_resets_the_counter(self):
        """الضابط المقابل: محاولتان خاطئتان لا تُراكمان على المندوب."""
        self.Driver._qd_authenticate('0551110001', '0000')
        self.Driver._qd_authenticate('0551110001', '7391')._qd_open_session()
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
        self.driver.pin = '8264'
        self.assertFalse(self.Driver._qd_driver_from_session(token),
                         'الجهاز القديم بقي داخلاً بعد تغيير الرمز')
        self.assertEqual(self.Driver._qd_authenticate('0551110001', '8264'),
                         self.driver)

    def test_revoking_sessions_logs_the_device_out(self):
        token = self.driver._qd_open_session()
        self.driver.action_revoke_sessions()
        self.assertFalse(self.Driver._qd_driver_from_session(token))

    def test_predictable_pins_are_refused(self):
        """القفل يحمي من تخمين مندوبٍ بعينه، لا من تجريب "1234" على
        كل المندوبين - ولا يُحتسب فشلٌ على من لم يُجرَّب رقمه بعد."""
        for weak in ('1234', '0000', '1111', '123456', '999999', '4321'):
            with self.assertRaises(ValidationError, msg=weak):
                self.Driver.create({'name': 'رمز متوقَّع',
                                    'phone': '0558881234', 'pin': weak})

    def test_a_strong_pin_is_accepted(self):
        """الضابط المقابل: المنع لم يُغلق الباب على الأرقام الصالحة."""
        driver = self.Driver.create({'name': 'رمز سليم',
                                     'phone': '0558882345', 'pin': '7391'})
        self.assertTrue(driver.has_pin)

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
        self.assertFalse(self.Driver._qd_authenticate('0551110001', '7391'))

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
            'webhook_url': 'http://merchant.invalid/hook',
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


@tagged('post_install', '-at_install')
class TestHomeScreen(QuickDeliveryCommon):
    """الصفحة الرئيسية: السوبرماركتات أيقوناتٍ، والأرقام من الخادم."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Home = cls.env['quick.delivery.home']
        cls.second = cls.env['res.partner'].create({
            'name': 'سوبرماركت الكروت', 'is_qcommerce_client': True,
            'api_key': 'HOME-KEY-2'})
        cls.dispatcher = cls.env['res.users'].create({
            'name': 'غرفة عمليات الرئيسية', 'login': 'home_dispatcher',
            'group_ids': [(6, 0, [
                cls.env.ref('quick_delivery.group_qd_dispatcher').id])]})
        cls.outsider = cls.env['res.users'].create({
            'name': 'مستخدم خارج التوصيل', 'login': 'home_outsider',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})

    def test_every_merchant_gets_a_tile(self):
        merchants = self.Home.get_home()['merchants']
        names = [m['name'] for m in merchants]
        self.assertIn(self.client.name, names)
        self.assertIn('سوبرماركت الكروت', names)

    def test_tiles_carry_each_merchants_own_numbers(self):
        """الغرض من الصفحة: حالة كل شركة من نظرة، لا مجموع الكل."""
        self._order(merchant_order_id='HOME-1', client_id=self.client.id)
        tiles = {m['name']: m for m in self.Home.get_home()['merchants']}
        self.assertEqual(tiles[self.client.name]['active_count'], 1)
        self.assertEqual(tiles['سوبرماركت الكروت']['active_count'], 0)

    def test_tiles_have_distinct_tones(self):
        merchants = self.Home.get_home()['merchants']
        self.assertNotEqual(merchants[0]['tone'], merchants[1]['tone'])

    def test_an_unconfigured_merchant_is_flagged(self):
        tiles = {m['name']: m for m in self.Home.get_home()['merchants']}
        self.assertFalse(tiles['سوبرماركت الكروت']['configured'],
                         'سوبرماركت بلا مفتاح ولا رابط إبلاغ عُدَّ مكتملاً')

    def test_the_kpis_cover_the_whole_operation(self):
        self._order(merchant_order_id='HOME-K1')
        kpis = self.Home.get_home()['kpis']
        self.assertGreaterEqual(kpis['active'], 1)
        for key in ('late', 'unassigned', 'online_drivers',
                    'delivered_today', 'cod_today'):
            self.assertIn(key, kpis)

    def test_a_dispatcher_may_open_the_home(self):
        data = self.Home.with_user(self.dispatcher).get_home()
        self.assertIn('merchants', data)

    @mute_logger('odoo.addons.base.models.ir_model', 'odoo.models')
    def test_an_outsider_may_not(self):
        """الصفحة تحمل جوالات العملاء وأرقام كل شركة."""
        with self.assertRaises(AccessError):
            self.Home.with_user(self.outsider).get_home()

    def test_the_manager_only_tool_is_hidden_from_a_dispatcher(self):
        keys = [e['key'] for e
                in self.Home.with_user(self.dispatcher).get_home()['extras']]
        self.assertNotIn('webhooks', keys)
        self.assertIn('drivers', keys)


@tagged('post_install', '-at_install')
class TestOthaimAdapter(QuickDeliveryCommon):
    """مُحوّل العثيم - كُتب من نداء حقيقي ملتقَط لا من وثيقة.

    الأجسام هنا هي نفسها التي وصلت في بروفة الربط.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Inbox = cls.env['quick.delivery.inbox']
        cls.othaim = cls.env['res.partner'].create({
            'name': 'شركة العثيم', 'is_qcommerce_client': True,
            'api_key': 'OTHAIM-ADAPTER-1', 'qd_payload_format': 'othaim'})

    def _body(self, **over):
        body = {
            'requestId': '6f1c2a90-3c4d-4a1e-9b77-0a5e21bb4410',
            'eventType': 'ORDER.READY_FOR_PICKUP',
            'apiVersion': '2.1',
            'payload': {
                'orderNumber': 'OTH-RYD-8841233',
                'branch': {
                    'code': 'RYD-0142',
                    'nameAr': 'العثيم – النرجس',
                    'nameEn': 'Othaim Al Narjis',
                    'geo': {'latitude': 24.8312, 'longitude': 46.6411},
                },
                'customer': {
                    'fullName': 'عبدالله محمد',
                    'mobileNumber': '+966551234567',
                    'address': {
                        'district': 'النرجس',
                        'street': 'شارع الأمير سلطان',
                        'buildingNo': '2314',
                        'additionalDirections': 'الدور الثاني، الشقة 5',
                        'geo': {'latitude': 24.8401, 'longitude': 46.6338},
                    },
                },
                'fulfillment': {'promisedMinutes': 30, 'toteCount': 4},
                'payment': {'paymentType': 'CASH_ON_DELIVERY',
                            'amountDue': {'value': 247.80,
                                          'currency': 'SAR'}},
            },
        }
        body['payload'].update(over.pop('payload', {}))
        body.update(over)
        return body

    def _capture(self, body):
        record = self.Inbox.create({
            'client_id': self.othaim.id,
            'raw_body': json.dumps(body, ensure_ascii=False),
        })
        record._qd_try_map()
        return record

    # ------------------------------------------------------- الإنشاء
    def test_an_othaim_order_becomes_a_real_order(self):
        record = self._capture(self._body())
        self.assertEqual(record.state, 'mapped', record.error)
        order = record.order_id
        self.assertTrue(order)
        self.assertEqual(order.merchant_order_id, 'OTH-RYD-8841233')
        self.assertEqual(order.client_id, self.othaim)

    def test_every_field_is_translated(self):
        order = self._capture(self._body()).order_id
        self.assertEqual(order.store_name, 'العثيم – النرجس')
        self.assertEqual(order.store_code, 'RYD-0142')
        self.assertAlmostEqual(order.store_lat, 24.8312, places=4)
        self.assertAlmostEqual(order.store_lng, 46.6411, places=4)
        self.assertEqual(order.customer_name, 'عبدالله محمد')
        self.assertEqual(order.customer_phone, '+966551234567')
        self.assertAlmostEqual(order.customer_lat, 24.8401, places=4)
        self.assertEqual(order.bags_count, 4)
        self.assertEqual(order.sla_minutes, 30)
        self.assertEqual(order.payment_method, 'COD')
        self.assertAlmostEqual(order.cod_amount, 247.80, places=2)

    def test_the_address_parts_become_one_readable_line(self):
        """المندوب يقرأ سطراً على جواله، لا كائن JSON."""
        order = self._capture(self._body()).order_id
        for part in ('النرجس', 'شارع الأمير سلطان', 'مبنى 2314',
                     'الدور الثاني'):
            self.assertIn(part, order.address_notes)

    def test_prepaid_orders_carry_no_collection(self):
        record = self._capture(self._body(payload={
            'orderNumber': 'OTH-RYD-PRE-1',
            'payment': {'paymentType': 'PREPAID_ONLINE',
                        'amountDue': {'value': 0, 'currency': 'SAR'}}}))
        self.assertEqual(record.state, 'mapped', record.error)
        self.assertEqual(record.order_id.payment_method, 'PREPAID')
        self.assertEqual(record.order_id.cod_amount, 0.0)

    def test_the_english_branch_name_is_used_when_arabic_is_absent(self):
        record = self._capture(self._body(payload={
            'orderNumber': 'OTH-RYD-EN-1',
            'branch': {'code': 'RYD-0142', 'nameEn': 'Othaim Al Narjis',
                       'geo': {'latitude': 24.83, 'longitude': 46.64}}}))
        self.assertEqual(record.order_id.store_name, 'Othaim Al Narjis')

    # ------------------------------------------------------- التكرار
    def test_a_resend_does_not_create_a_second_order(self):
        """أنظمتهم تُعيد المحاولة عند انقطاع."""
        first = self._capture(self._body())
        second = self._capture(self._body())
        self.assertEqual(second.state, 'mapped')
        self.assertEqual(second.order_id, first.order_id,
                         'إعادة الإرسال أنشأت طلباً ثانياً')
        self.assertIn('موجود مسبقاً', second.result_note)

    # ------------------------------------------------------- النواقص
    def test_a_missing_customer_location_is_refused_by_name(self):
        """الحالة الواقعية: طلب من مركز اتصال بعنوان نصّي.

        الرسالة تُسمّي المصدر: تُطالب التاجر ببيان، لا تبحث في كودك.
        """
        body = self._body(payload={'orderNumber': 'OTH-RYD-NOGEO'})
        body['payload']['customer']['address'].pop('geo')
        record = self._capture(body)
        self.assertEqual(record.state, 'failed')
        self.assertIn('العثيم لم يرسل', record.error)
        self.assertIn('موقع العميل', record.error)

    def test_a_missing_branch_location_is_refused(self):
        body = self._body(payload={'orderNumber': 'OTH-RYD-NOSTORE'})
        body['payload']['branch'].pop('geo')
        self.assertEqual(self._capture(body).state, 'failed')

    def test_an_unknown_payment_type_is_refused(self):
        record = self._capture(self._body(payload={
            'orderNumber': 'OTH-RYD-PAY',
            'payment': {'paymentType': 'CRYPTO'}}))
        self.assertEqual(record.state, 'failed')
        self.assertIn('طريقة دفع غير معروفة', record.error)

    def test_a_missing_order_number_is_refused(self):
        body = self._body()
        body['payload'].pop('orderNumber')
        record = self._capture(body)
        self.assertEqual(record.state, 'failed')
        self.assertIn('orderNumber', record.error)

    # ------------------------------------------------------- الأحداث
    def test_a_merchant_cancellation_cancels_the_order(self):
        """مندوب يقود إلى طلب أُلغي قبل ربع ساعة خسارة حقيقية."""
        created = self._capture(self._body()).order_id
        record = self._capture({
            'eventType': 'ORDER.CANCELLED_BY_MERCHANT',
            'payload': {'orderNumber': 'OTH-RYD-8841233',
                        'cancellationReason': 'ITEMS_OUT_OF_STOCK'}})
        self.assertEqual(record.state, 'mapped', record.error)
        created.invalidate_recordset()
        self.assertEqual(created.state, 'cancelled')
        self.assertEqual(created.failure_reason, 'cancelled_by_merchant')
        self.assertIn('ITEMS_OUT_OF_STOCK', created.failure_notes)

    def test_cancelling_releases_the_driver(self):
        """الضابط العملي: المندوب لا يبقى محجوزاً على طلب ملغى.

        الإسناد هنا يدوي: فرع النرجس يبعد نحو 13 كم عن موقع مندوب
        الاختبار، ونطاق الإسناد التلقائي 6 كم - فلا يُسنَد تلقائياً،
        وهذا سلوك صحيح لا خلل.
        """
        created = self._capture(self._body()).order_id
        created.write({'driver_id': self.driver.id,
                       'state': 'driver_assigned'})
        self.driver.sudo().driver_status = 'busy'
        self._capture({
            'eventType': 'ORDER.CANCELLED_BY_MERCHANT',
            'payload': {'orderNumber': 'OTH-RYD-8841233'}})
        self.driver.invalidate_recordset()
        self.assertEqual(self.driver.driver_status, 'online')

    def test_cancelling_an_unknown_order_is_a_clear_error(self):
        record = self._capture({
            'eventType': 'ORDER.CANCELLED_BY_MERCHANT',
            'payload': {'orderNumber': 'OTH-NOT-OURS'}})
        self.assertEqual(record.state, 'failed')
        self.assertIn('غير موجود', record.error)

    def test_an_unrelated_event_is_ignored_not_failed(self):
        """يدفعون أحداثهم كلها على مسار واحد: حشرها في "تعذّر" يُغرق
        الشاشة بأحمر كاذب فيضيع العطل الحقيقي بينه."""
        record = self._capture({
            'eventType': 'LOYALTY.POINTS_UPDATED',
            'payload': {'orderNumber': 'OTH-RYD-8841233'}})
        self.assertEqual(record.state, 'ignored')
        self.assertFalse(record.error)
        self.assertIn('LOYALTY.POINTS_UPDATED', record.result_note)

    def test_an_ignored_record_is_not_replayed(self):
        record = self._capture({'eventType': 'LOYALTY.POINTS_UPDATED',
                                'payload': {}})
        before = record.attempts
        record.action_replay()
        self.assertEqual(record.attempts, before,
                         'المُهمَل يُعاد معالجته بلا داعٍ')

    # ------------------------------------------------- الصيغة الأصلية
    def test_the_native_format_still_works(self):
        """الضابط المقابل: إضافة صيغة تاجر لم تكسر صيغتنا."""
        native_client = self.env['res.partner'].create({
            'name': 'عميل بالصيغة الأصلية', 'is_qcommerce_client': True,
            'api_key': 'NATIVE-STILL-1'})
        record = self.Inbox.create({
            'client_id': native_client.id,
            'raw_body': json.dumps({
                'order_id': 'NATIVE-1',
                'store': {'store_name': 'فرع', 'lat': 24.71, 'lng': 46.67},
                'customer': {'name': 'عميل', 'phone': '0550000000',
                             'lat': 24.72, 'lng': 46.68},
                'payment': {'method': 'PREPAID'},
            }, ensure_ascii=False)})
        record._qd_try_map()
        self.assertEqual(record.state, 'mapped', record.error)
        self.assertEqual(record.order_id.merchant_order_id, 'NATIVE-1')


@tagged('post_install', '-at_install')
class TestCustomerMessaging(QuickDeliveryCommon):
    """إيصال رمز الاستلام إلى العميل - واتساب ثم رسالة نصية.

    الشبكة لا تُستدعى هنا: ما يُختبر هو بناء الرسالة، واختيار القناة،
    والتراجع عند الفشل، وألا تُرسل رسالتان للطلب الواحد.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env['quick.delivery.channel']
        cls.Message = cls.env['quick.delivery.message']
        cls.Channel.search([]).unlink()
        cls.whatsapp = cls.Channel.create({
            'name': 'واتساب', 'kind': 'whatsapp', 'sequence': 1,
            'wa_phone_uid': '123456789', 'wa_token': 'TOKEN-X',
            'wa_template_name': 'delivery_otp_ar',
            'message_template': '{merchant}\n{driver}\n{otp}\n{tracking_url}',
        })
        cls.sms = cls.Channel.create({
            'name': 'رسالة نصية', 'kind': 'taqnyat', 'sequence': 20,
            'endpoint_url': 'http://sms-provider.invalid/send',
            'api_key': 'SMS-KEY', 'sender_name': 'DELIVERY',
            'headers_json': '{"Content-Type": "application/json"}',
            'body_template': '{"recipients": ["{phone}"],'
                             ' "body": "{message}"}',
        })

    # ------------------------------------------------------- الأرقام
    def test_saudi_numbers_are_normalised(self):
        """المزوّدون وميتا يرفضون 05XXXXXXXX أو يُرسلونها لبلد آخر."""
        from odoo.addons.quick_delivery.models.messaging import normalize_phone
        for raw in ('0551234567', '+966551234567', '00966551234567',
                    '966551234567', '551234567', '055 123 4567'):
            self.assertEqual(normalize_phone(raw), '966551234567', raw)

    def test_an_empty_number_yields_nothing(self):
        from odoo.addons.quick_delivery.models.messaging import normalize_phone
        self.assertEqual(normalize_phone(''), '')
        self.assertEqual(normalize_phone(None), '')

    # ------------------------------------------------------ الإنشاء
    def test_assigning_a_driver_queues_the_message(self):
        order = self._order(merchant_order_id='MSG-1')
        self.assertEqual(order.driver_id, self.driver)
        message = self.Message.search([('order_id', '=', order.id)])
        self.assertEqual(len(message), 1)
        self.assertEqual(message.state, 'pending')

    def test_the_body_carries_the_code_and_the_link(self):
        order = self._order(merchant_order_id='MSG-2')
        message = self.Message.search([('order_id', '=', order.id)])
        self.assertIn(order.sudo().delivery_otp, message.body)
        self.assertIn(order.tracking_url, message.body)
        self.assertIn(self.driver.name, message.body)

    def test_the_phone_is_the_customers(self):
        order = self._order(merchant_order_id='MSG-3',
                            customer_phone='0509998888')
        message = self.Message.search([('order_id', '=', order.id)])
        self.assertEqual(message.phone, '0509998888')

    def test_no_second_message_for_the_same_order(self):
        """إعادة إسناد المندوب لا تُرسل رمزاً ثانياً للعميل."""
        order = self._order(merchant_order_id='MSG-4')
        other = self.Driver.create({
            'name': 'مندوب بديل للرسائل', 'phone': '0557770001',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753})
        order.write({'driver_id': other.id})
        self.assertEqual(
            self.Message.search_count([('order_id', '=', order.id)]), 1)

    def test_a_merchant_may_opt_out(self):
        """لكل رسالة تكلفة: من يُوصل الرمز بنفسه لا نُرسل لعميله."""
        self.client.qd_sms_customer = False
        order = self._order(merchant_order_id='MSG-OFF')
        self.assertFalse(self.Message.search_count(
            [('order_id', '=', order.id)]))
        self.client.qd_sms_customer = True

    def test_an_unassigned_order_sends_nothing(self):
        """قبل الإسناد لا مندوب يُذكر اسمه، ولا خبر عند العميل بعد."""
        self.driver.driver_status = 'offline'
        order = self._order(merchant_order_id='MSG-NODRV')
        self.assertFalse(order.driver_id)
        self.assertFalse(self.Message.search_count(
            [('order_id', '=', order.id)]))

    # ------------------------------------------------------ واتساب
    def test_the_whatsapp_payload_matches_the_template_order(self):
        """نصّ القالب ثابت عند ميتا: نملك ملء فراغاته بترتيبها فقط."""
        sent = {}

        def fake_post(url, json=None, headers=None, timeout=None, **kw):
            sent['url'] = url
            sent['json'] = json
            sent['headers'] = headers

            class Response:
                status_code = 200
                text = '{"messages":[{"id":"wamid.X"}]}'
            return Response()

        from odoo.addons.quick_delivery.models import messaging
        original = messaging.requests.post
        messaging.requests.post = fake_post
        try:
            ok, code, error = self.whatsapp._qd_send(
                '0551234567', 'العثيم\nخالد\n123456\nhttps://x/track/y')
        finally:
            messaging.requests.post = original

        self.assertTrue(ok, error)
        self.assertIn('123456789/messages', sent['url'])
        self.assertIn('Bearer TOKEN-X', sent['headers']['Authorization'])
        body = sent['json']
        self.assertEqual(body['to'], '966551234567')
        self.assertEqual(body['type'], 'template')
        self.assertEqual(body['template']['name'], 'delivery_otp_ar')
        values = [p['text'] for p
                  in body['template']['components'][0]['parameters']]
        self.assertEqual(values,
                         ['العثيم', 'خالد', '123456', 'https://x/track/y'])

    def test_whatsapp_without_credentials_fails_clearly(self):
        bare = self.Channel.create({
            'name': 'واتساب بلا بيانات', 'kind': 'whatsapp',
            'message_template': '{otp}'})
        ok, code, error = bare._qd_send('0551234567', '123456')
        self.assertFalse(ok)
        self.assertIn('غير مضبوط', error)

    def test_whatsapp_without_a_template_name_fails_clearly(self):
        channel = self.Channel.create({
            'name': 'واتساب بلا قالب', 'kind': 'whatsapp',
            'wa_phone_uid': '1', 'wa_token': 't',
            'message_template': '{otp}'})
        ok, code, error = channel._qd_send('0551234567', '123456')
        self.assertFalse(ok)
        self.assertIn('قالب', error)

    # ------------------------------------------------------ التراجع
    def test_the_second_channel_is_tried_when_the_first_fails(self):
        """عميل بلا واتساب أو حاجب لرقمنا موجود دائماً."""
        calls = []

        def fake_send(self_channel, phone, message):
            calls.append(self_channel.name)
            if self_channel.kind == 'whatsapp':
                return False, 400, 'recipient not on whatsapp'
            return True, 200, ''

        order = self._order(merchant_order_id='MSG-FB')
        message = self.Message.search([('order_id', '=', order.id)])
        from odoo.addons.quick_delivery.models.messaging import (
            QuickDeliveryChannel)
        original = QuickDeliveryChannel._qd_send
        QuickDeliveryChannel._qd_send = fake_send
        try:
            message._deliver()
        finally:
            QuickDeliveryChannel._qd_send = original

        self.assertEqual(calls, ['واتساب', 'رسالة نصية'])
        self.assertEqual(message.state, 'sent')
        self.assertEqual(message.channel_id, self.sms)

    def test_failing_everywhere_is_retried_not_dropped(self):
        def fake_send(self_channel, phone, message):
            return False, 500, 'provider down'

        order = self._order(merchant_order_id='MSG-DOWN')
        message = self.Message.search([('order_id', '=', order.id)])
        from odoo.addons.quick_delivery.models.messaging import (
            QuickDeliveryChannel)
        original = QuickDeliveryChannel._qd_send
        QuickDeliveryChannel._qd_send = fake_send
        try:
            message._deliver()
        finally:
            QuickDeliveryChannel._qd_send = original

        self.assertEqual(message.state, 'pending', 'الرسالة أُسقطت بلا رجعة')
        self.assertEqual(message.attempts, 1)
        self.assertIn('واتساب', message.last_error)
        self.assertIn('رسالة نصية', message.last_error)

    def test_a_sent_message_is_never_resent(self):
        order = self._order(merchant_order_id='MSG-ONCE')
        message = self.Message.search([('order_id', '=', order.id)])
        message.write({'state': 'sent'})
        calls = []

        def fake_send(self_channel, phone, body):
            calls.append(1)
            return True, 200, ''

        from odoo.addons.quick_delivery.models.messaging import (
            QuickDeliveryChannel)
        original = QuickDeliveryChannel._qd_send
        QuickDeliveryChannel._qd_send = fake_send
        try:
            message._deliver()
        finally:
            QuickDeliveryChannel._qd_send = original
        self.assertFalse(calls, 'أُعيد إرسال رسالة مُرسلة')

    def test_no_channel_at_all_is_recorded_not_silent(self):
        order = self._order(merchant_order_id='MSG-NOCH')
        message = self.Message.search([('order_id', '=', order.id)])
        self.Channel.search([]).write({'active': False})
        try:
            message._deliver()
        finally:
            self.Channel.with_context(active_test=False).search(
                []).write({'active': True})
        self.assertEqual(message.state, 'failed')
        self.assertIn('لا قناة', message.last_error)

    # ------------------------------------------------- الرسالة النصية
    def test_an_internal_url_is_refused(self):
        """رابطٌ يشير إلى داخل الشبكة يجعل الخادم أداةً للوصول إلى ما
        لا يصله المستخدم - وأخطره عنوان بيانات السحابة."""
        for url in ('http://169.254.169.254/latest/meta-data/',
                    'http://127.0.0.1:8069/web',
                    'http://localhost/x'):
            self.sms.endpoint_url = url
            ok, code, error = self.sms._qd_send('0551234567', 'نص')
            self.assertFalse(ok, url)
            self.assertIn('داخلي', error + ' ')
        self.sms.endpoint_url = 'http://sms-provider.invalid/send'

    def test_a_non_http_scheme_is_refused(self):
        self.sms.endpoint_url = 'file:///etc/passwd'
        ok, code, error = self.sms._qd_send('0551234567', 'نص')
        self.assertFalse(ok)
        self.sms.endpoint_url = 'http://sms-provider.invalid/send'

    def test_the_sms_body_is_valid_json_with_arabic_and_newlines(self):
        """سطر جديد أو علامة اقتباس في رسالة عربية كان يُفسد الجسم."""
        sent = {}

        def fake_post(url, data=None, headers=None, timeout=None, **kw):
            sent['data'] = data

            class Response:
                status_code = 200
                text = 'OK'
            return Response()

        from odoo.addons.quick_delivery.models import messaging
        original = messaging.requests.post
        messaging.requests.post = fake_post
        try:
            self.sms._qd_send('0551234567',
                              'طلبك من "العثيم"\nالرمز: 123456')
        finally:
            messaging.requests.post = original

        parsed = json.loads(sent['data'].decode('utf-8'))
        self.assertEqual(parsed['recipients'], ['966551234567'])
        self.assertIn('العثيم', parsed['body'])
        self.assertIn('\n', parsed['body'])


@tagged('post_install', '-at_install')
class TestHardening(QuickDeliveryCommon):
    """ثغرات وُجدت في مراجعة، وضوابطها."""

    def _ready_order(self, ref):
        order = self._order(merchant_order_id=ref)
        if not order.driver_id:
            order.write({'driver_id': self.driver.id,
                         'state': 'driver_assigned'})
        order.write({'state': 'picked_up'})
        return order

    # ----------------------------------------- مدى إحداثيات المندوب
    def test_an_impossible_position_is_refused(self):
        """جوال معطوب أو نداء مُلفَّق كان يضع المندوب خارج الكرة."""
        with self.assertRaises(ValidationError):
            self.driver.write({'current_lat': 999.0})
        with self.assertRaises(ValidationError):
            self.driver.write({'current_lng': -200.0})

    def test_a_real_position_passes(self):
        self.driver.write({'current_lat': 21.4858, 'current_lng': 39.1925})
        self.assertAlmostEqual(self.driver.current_lat, 21.4858, places=4)

    # ------------------------------------------- سبب عدم الإسناد
    def test_an_unassigned_order_says_why_no_driver_is_online(self):
        self.driver.driver_status = 'offline'
        order = self._order(merchant_order_id='HARD-WHY-1')
        self.assertFalse(order.driver_id)
        self.assertIn('غير متصل', order.dispatch_note)

    def test_it_says_when_the_nearest_driver_is_too_far(self):
        """الرسالة تقول القرار: وسّع النطاق أو قرّب مندوباً."""
        self.driver.write({'current_lat': 21.4858,
                           'current_lng': 39.1925})      # جدة
        order = self._order(merchant_order_id='HARD-WHY-2')
        self.assertFalse(order.driver_id)
        self.assertIn('كم', order.dispatch_note)
        self.assertIn('النطاق', order.dispatch_note)

    def test_it_says_when_everyone_is_busy(self):
        first = self._order(merchant_order_id='HARD-WHY-3')
        self.assertEqual(first.driver_id, self.driver)
        second = self._order(merchant_order_id='HARD-WHY-4')
        self.assertFalse(second.driver_id)
        self.assertIn('طلبات أخرى', second.dispatch_note)

    def test_it_says_when_locations_are_unknown(self):
        self.driver.write({'current_lat': 0.0, 'current_lng': 0.0})
        order = self._order(merchant_order_id='HARD-WHY-5')
        self.assertFalse(order.driver_id)
        self.assertIn('التطبيق', order.dispatch_note)

    def test_the_note_is_cleared_once_assigned(self):
        """الضابط المقابل: سببٌ قديم باقٍ على طلب أُسند يُضلّل."""
        self.driver.driver_status = 'offline'
        order = self._order(merchant_order_id='HARD-WHY-6')
        self.assertTrue(order.dispatch_note)
        self.driver.write({'driver_status': 'online',
                           'current_lat': 24.7136, 'current_lng': 46.6753})
        order.auto_assign_nearest_driver()
        self.assertEqual(order.driver_id, self.driver)
        self.assertFalse(order.dispatch_note)
