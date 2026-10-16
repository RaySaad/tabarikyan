# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFleetMaintenance(TransactionCase):
    """الصيانة بالمسافة والزمن - وهو ما لا تقدّمه أودو قياسياً."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'ماركة الصيانة'})
        model = cls.env['fleet.vehicle.model'].create({
            'name': 'موديل الصيانة', 'brand_id': brand.id})
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'license_plate': 'MNT-1',
            'odometer': 10000.0})
        cls.oil = cls.env['fleet.service.type'].create({
            'name': 'تغيير زيت', 'category': 'service'})

    def _plan(self, **vals):
        return self.env['fleet.maintenance.plan'].create(dict({
            'vehicle_id': self.vehicle.id,
            'service_type_id': self.oil.id,
            'interval_km': 5000,
            'warning_km': 500,
            'last_service_odometer': 10000.0,
            'last_service_date': date(2026, 1, 1),
        }, **vals))

    def _set_odometer(self, value):
        self.env['fleet.vehicle.odometer'].create({
            'vehicle_id': self.vehicle.id, 'value': value,
            'date': date(2026, 3, 1)})
        self.vehicle.invalidate_recordset()

    # ---- الجدولة بالمسافة ----
    def test_due_distance_is_computed_from_the_last_service(self):
        plan = self._plan()
        self.assertEqual(plan.next_due_odometer, 15000.0)
        self.assertEqual(plan.state, 'ok')

    def test_warning_starts_before_the_due_distance(self):
        """التنبيه مبكر: قبل 500 كم من الاستحقاق لا عنده."""
        plan = self._plan()
        self._set_odometer(14600.0)
        plan._compute_due()

        self.assertEqual(plan.state, 'warning')
        self.assertAlmostEqual(plan.remaining_km, 400.0, places=1)

    def test_passing_the_due_distance_is_overdue(self):
        plan = self._plan()
        self._set_odometer(15200.0)
        plan._compute_due()

        self.assertEqual(plan.state, 'overdue')
        self.assertLess(plan.remaining_km, 0)

    # ---- الجدولة بالزمن ----
    def test_due_date_is_computed_from_the_last_service(self):
        plan = self._plan(interval_km=0, interval_days=90,
                          last_service_date=date(2026, 1, 1))
        self.assertEqual(plan.next_due_date, date(2026, 1, 1) + timedelta(days=90))

    def test_whichever_comes_first_decides(self):
        """دورة بالمسافة والزمن معاً: السابق منهما يحكم."""
        today = date.today()
        plan = self._plan(interval_km=5000, interval_days=30,
                          last_service_date=today - timedelta(days=29))
        # المسافة بعيدة، لكن الزمن على وشك الاستحقاق
        self.assertEqual(plan.state, 'warning')

    def test_a_plan_without_any_interval_is_unplanned(self):
        plan = self._plan(interval_km=0, interval_days=0)
        self.assertEqual(plan.state, 'unplanned')

    # ---- التنفيذ يعيد الجدولة ----
    def test_registering_a_service_starts_the_next_cycle(self):
        plan = self._plan()
        self._set_odometer(15100.0)
        plan._compute_due()
        self.assertEqual(plan.state, 'overdue')

        wizard = self.env['fleet.maintenance.execute.wizard'].with_context(
            default_plan_id=plan.id).create({
                'plan_id': plan.id, 'date': date(2026, 3, 5),
                'odometer': 15100.0, 'amount': 320.0})
        wizard.action_confirm()

        self.assertEqual(plan.last_service_odometer, 15100.0)
        self.assertEqual(plan.next_due_odometer, 20100.0)
        self.assertEqual(plan.state, 'ok', 'بقيت متأخرة بعد التنفيذ')
        self.assertEqual(plan.service_count, 1)

    def test_execution_writes_a_service_log_with_its_cost(self):
        plan = self._plan()
        self.env['fleet.maintenance.execute.wizard'].create({
            'plan_id': plan.id, 'date': date(2026, 3, 5),
            'odometer': 15000.0, 'amount': 450.0}).action_confirm()

        log = self.env['fleet.vehicle.log.services'].search([
            ('vehicle_id', '=', self.vehicle.id),
            ('service_type_id', '=', self.oil.id)], limit=1)
        self.assertTrue(log, 'لم يُكتب سجل الخدمة')
        self.assertAlmostEqual(log.amount, 450.0, places=2)

    def test_an_odometer_reading_below_the_last_service_is_refused(self):
        plan = self._plan()
        wizard = self.env['fleet.maintenance.execute.wizard'].create({
            'plan_id': plan.id, 'date': date(2026, 3, 5), 'odometer': 9000.0})
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # ---- التنبيه ----
    def test_the_cron_notifies_once_per_cycle_not_daily(self):
        plan = self._plan()
        self._set_odometer(14700.0)

        self.env['fleet.maintenance.plan']._cron_check_due()
        first = len(plan.activity_ids)
        self.env['fleet.maintenance.plan']._cron_check_due()

        self.assertEqual(first, 1, 'لم يُنشأ تنبيه')
        self.assertEqual(len(plan.activity_ids), 1, 'تكرر التنبيه يومياً')

    def test_executing_the_service_closes_the_warning_activity(self):
        plan = self._plan()
        self._set_odometer(14700.0)
        self.env['fleet.maintenance.plan']._cron_check_due()
        self.assertTrue(plan.activity_ids)

        self.env['fleet.maintenance.execute.wizard'].create({
            'plan_id': plan.id, 'date': date(2026, 3, 5),
            'odometer': 14700.0}).action_confirm()

        self.assertFalse(plan.activity_ids, 'بقي التنبيه بعد تنفيذ الصيانة')


@tagged('post_install', '-at_install')
class TestFleetDashboardData(TransactionCase):
    """اللوحة تقرأ بلا أخطاء حتى على قاعدة فارغة."""

    def test_dashboard_returns_its_sections(self):
        data = self.env['fleet.dashboard'].get_dashboard_data()
        for key in ('period', 'kpi', 'by_branch', 'top_cost', 'idle_list', 'due_list'):
            self.assertIn(key, data)
        for key in ('vehicles', 'rented', 'idle', 'utilisation',
                    'overdue_maintenance', 'rent_posted'):
            self.assertIn(key, data['kpi'])

    def test_cost_report_is_queryable(self):
        """عرض SQL: نتأكد أنه يُستعلم بلا خطأ (أعمدة وتجميع صحيحة)."""
        self.env['fleet.vehicle.cost.report'].search([], limit=5)
        self.env['fleet.vehicle.cost.report'].read_group(
            [], ['rent_amount:sum', 'net_result:sum'], ['vehicle_id'])
