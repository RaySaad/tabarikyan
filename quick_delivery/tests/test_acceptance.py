# -*- coding: utf-8 -*-
"""قبول المندوب للطلب - وما يحدث حين لا يقبل.

الثغرة التي تعالجها هذه الاختبارات: الإسناد كان جبراً بلا قبول، ومجدول
إعادة البحث يلتقط "جاري البحث" وحده. فطلبٌ أُسنِد لمندوب نائم يبقى
عنده إلى الأبد، وهو يبقى "مشغولاً" فلا تصله طلبات أخرى - طلبٌ ضائع
ومندوبٌ معطَّل بسبب واحد.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.quick_delivery.models import delivery_order as do_module
from .test_quick_delivery import QuickDeliveryCommon


@tagged('post_install', '-at_install')
class TestAcceptance(QuickDeliveryCommon):

    def _age_assignment(self, order, seconds):
        """يُقدّم وقت الإسناد إلى الماضي - بدل انتظار دقيقة فعلية."""
        order.sudo().write({
            'assigned_at': fields.Datetime.now() - timedelta(seconds=seconds),
        })

    # ------------------------------------------------------- القبول
    def test_a_new_assignment_is_not_accepted_yet(self):
        order = self._order(merchant_order_id='ACC-1')
        self.assertEqual(order.state, 'driver_assigned')
        self.assertFalse(order.accepted_at)
        self.assertEqual(order.assign_attempts, 1)

    def test_accepting_stops_the_clock(self):
        order = self._order(merchant_order_id='ACC-2')
        order._qd_accept(self.driver)
        self.assertTrue(order.accepted_at)
        self.assertEqual(order._accept_seconds_left(), 0)

    def test_accepting_twice_is_harmless(self):
        order = self._order(merchant_order_id='ACC-3')
        order._qd_accept(self.driver)
        first = order.accepted_at
        order._qd_accept(self.driver)
        self.assertEqual(order.accepted_at, first)

    def test_another_driver_cannot_accept_your_order(self):
        other = self.env['quick.delivery.driver'].create(
            {'name': 'مندوب غريب', 'phone': '0559990001'})
        order = self._order(merchant_order_id='ACC-4')
        with self.assertRaises(UserError):
            order._qd_accept(other)

    def test_the_countdown_shrinks_with_time(self):
        order = self._order(merchant_order_id='ACC-5')
        self.assertGreater(order._accept_seconds_left(), 0)
        self._age_assignment(order, 45)
        self.assertLessEqual(order._accept_seconds_left(), 15)
        self._age_assignment(order, 120)
        self.assertEqual(order._accept_seconds_left(), 0)

    def test_the_timeout_is_one_minute_by_default(self):
        self.assertEqual(self.Order._accept_timeout_seconds(), 60)

    def test_the_timeout_is_configurable(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'quick_delivery.accept_timeout_seconds', '180')
        self.assertEqual(self.Order._accept_timeout_seconds(), 180)

    def test_a_broken_timeout_setting_falls_back(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'quick_delivery.accept_timeout_seconds', 'سريع')
        self.assertEqual(self.Order._accept_timeout_seconds(),
                         do_module.DEFAULT_ACCEPT_TIMEOUT_SECONDS)

    # ------------------------------------------------------- الردّ
    def test_declining_frees_the_order_at_once(self):
        """الرفض الصريح أصدق من الصمت - ولا ينتظر المهلة."""
        order = self._order(merchant_order_id='DEC-1')
        order._qd_decline(self.driver, 'مركبتي تعطّلت')
        self.assertEqual(order.state, 'searching_driver')
        self.assertFalse(order.driver_id)
        self.assertEqual(self.driver.driver_status, 'online')

    def test_declining_is_recorded_with_its_reason(self):
        order = self._order(merchant_order_id='DEC-2')
        order._qd_decline(self.driver, 'مركبتي تعطّلت')
        decline = self.env['quick.delivery.decline'].search(
            [('order_id', '=', order.id)])
        self.assertEqual(len(decline), 1)
        self.assertEqual(decline.kind, 'declined')
        self.assertEqual(decline.reason, 'مركبتي تعطّلت')
        self.assertEqual(decline.driver_id, self.driver)

    def test_a_driver_who_declined_is_not_offered_it_again(self):
        """بلا استبعاد يعود الإسناد إليه بعد ثوانٍ لأنه الأقرب."""
        order = self._order(merchant_order_id='DEC-3')
        order._qd_decline(self.driver, '')
        order.auto_assign_nearest_driver()
        self.assertEqual(order.state, 'searching_driver')
        self.assertFalse(order.driver_id)
        self.assertIn('تخلّى عنه', order.dispatch_note or '')

    def test_he_may_still_take_other_orders(self):
        """الاستبعاد للطلب وحده لا للمندوب."""
        first = self._order(merchant_order_id='DEC-4')
        first._qd_decline(self.driver, '')
        second = self._order(merchant_order_id='DEC-5')
        self.assertEqual(second.driver_id, self.driver)

    def test_an_order_in_progress_cannot_be_declined(self):
        order = self._order(merchant_order_id='DEC-6')
        order._qd_accept(self.driver)
        order.write({'state': 'arrived_at_store'})
        with self.assertRaises(UserError):
            order._qd_decline(self.driver, '')

    def test_another_driver_cannot_decline_your_order(self):
        other = self.env['quick.delivery.driver'].create(
            {'name': 'مندوب غريب ثانٍ', 'phone': '0559990002'})
        order = self._order(merchant_order_id='DEC-7')
        with self.assertRaises(UserError):
            order._qd_decline(other, '')

    # ------------------------------------------------------- المهلة
    def test_an_unaccepted_order_is_reclaimed_after_the_timeout(self):
        order = self._order(merchant_order_id='TMO-1')
        self._age_assignment(order, 90)
        self.Order.cron_reclaim_stalled_assignments()
        self.assertFalse(order.driver_id)
        self.assertIn(order.state, ('searching_driver',))

    def test_an_accepted_order_is_never_reclaimed(self):
        """المندوب في طريقه إلى الفرع - سحبه منه خسارة لا إنقاذ."""
        order = self._order(merchant_order_id='TMO-2')
        order._qd_accept(self.driver)
        self._age_assignment(order, 600)
        self.Order.cron_reclaim_stalled_assignments()
        self.assertEqual(order.driver_id, self.driver)
        self.assertEqual(order.state, 'driver_assigned')

    def test_a_fresh_assignment_is_left_alone(self):
        order = self._order(merchant_order_id='TMO-3')
        self.Order.cron_reclaim_stalled_assignments()
        self.assertEqual(order.driver_id, self.driver)

    def test_the_timeout_is_recorded_as_no_response(self):
        order = self._order(merchant_order_id='TMO-4')
        self._age_assignment(order, 90)
        self.Order.cron_reclaim_stalled_assignments()
        decline = self.env['quick.delivery.decline'].search(
            [('order_id', '=', order.id)])
        self.assertEqual(decline.kind, 'timeout')
        self.assertGreaterEqual(decline.seconds_waited, 90)

    def test_a_disabled_timeout_reclaims_nothing(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'quick_delivery.accept_timeout_seconds', '0')
        order = self._order(merchant_order_id='TMO-5')
        self._age_assignment(order, 9000)
        self.Order.cron_reclaim_stalled_assignments()
        self.assertEqual(order.driver_id, self.driver)

    # ------------------------------------------- إخراج غير المستجيب
    def test_two_missed_deadlines_take_him_offline(self):
        """جواله مات أو انتهت ورديته - وإبقاؤه متاحاً يُسقط الطلبات."""
        limit = do_module.MAX_MISSED_BEFORE_OFFLINE
        for index in range(limit):
            order = self._order(merchant_order_id='OFF-%d' % index)
            self.assertEqual(order.driver_id, self.driver,
                             'لم يُسنَد في الجولة %d' % index)
            self._age_assignment(order, 90)
            self.Order.cron_reclaim_stalled_assignments()
            if index < limit - 1:
                self.driver.sudo().write({'driver_status': 'online'})
        self.assertEqual(self.driver.missed_assignments, limit)
        self.assertEqual(self.driver.driver_status, 'offline')

    def test_accepting_clears_his_record(self):
        self.driver.sudo().write({'missed_assignments': 1})
        order = self._order(merchant_order_id='OFF-CLR')
        order._qd_accept(self.driver)
        self.assertEqual(self.driver.missed_assignments, 0)

    # ------------------------------------------------------- التصعيد
    def test_after_the_attempt_limit_it_goes_to_the_ops_room(self):
        """الدوران بلا نهاية يُخفي المشكلة حتى ينتهي وقت الطلب صامتاً."""
        limit = do_module.MAX_DISPATCH_ATTEMPTS
        drivers = [self.driver]
        for index in range(limit - 1):
            drivers.append(self.env['quick.delivery.driver'].create({
                'name': 'مندوب تدوير %d' % index,
                'phone': '05533300%02d' % index,
                'driver_status': 'online',
                'current_lat': self.driver.current_lat,
                'current_lng': self.driver.current_lng,
            }))
        order = self._order(merchant_order_id='ESC-1')
        for _unused in range(limit):
            self.assertTrue(order.driver_id, 'توقّف التدوير مبكّراً')
            order._qd_decline(order.driver_id, '')
            order.auto_assign_nearest_driver()

        self.assertTrue(order.needs_attention)
        self.assertFalse(order.driver_id)
        self.assertIn('يدوياً', order.dispatch_note or '')

    def test_an_escalated_order_is_skipped_by_auto_dispatch(self):
        order = self._order(merchant_order_id='ESC-2')
        order.sudo().write({'needs_attention': True})
        order._qd_decline(self.driver, '')
        order.auto_assign_nearest_driver()
        self.assertFalse(order.driver_id)

    def test_the_decline_log_counts_per_order(self):
        order = self._order(merchant_order_id='ESC-3')
        order._qd_decline(self.driver, 'أول')
        order.invalidate_recordset()
        self.assertEqual(order.decline_count, 1)
        # نفس المندوب لا يُسجَّل مرتين لنفس الطلب
        self.env['quick.delivery.decline']._record(
            order, self.driver, 'timeout', 'ثانٍ')
        order.invalidate_recordset()
        self.assertEqual(order.decline_count, 1)
