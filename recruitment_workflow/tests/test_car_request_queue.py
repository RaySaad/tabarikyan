# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCarRequestQueue(TransactionCase):
    """طابور طلبات السيارات: الأقدمية تحكم، والعاجل استثناء بيد مسؤول
    المشروع وحده، وتحرّر مركبة ينبّه من ينتظرها."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create(
            {'name': 'منصة الطابور (اختبار)'})
        cls.pm = cls.env['res.users'].create({
            'name': 'مسؤول منصة الطابور', 'login': 'queue_pm',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_project_manager').id),
            ],
        })
        cls.fleet_user = cls.env['res.users'].create({
            'name': 'موظف الأسطول (طابور)', 'login': 'queue_fleet',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_fleet').id),
            ],
        })
        cls.model = cls.env['fleet.vehicle.model'].search([], limit=1)

    # ------------------------------------------------------------------
    def _make_request(self, name_suffix, urgent=False):
        request = self.env['recruitment.request'].create({
            'employee_name': 'مندوب %s' % name_suffix,
            'identification_id': '200000000%s' % name_suffix,
            'mobile': '05000000%s0' % name_suffix,
            'email': 'queue%s@example.com' % name_suffix,
            'project_id': self.project.id,
        })
        request.write({
            'car_requested': True,
            'car_request_state': 'waiting',
            'car_request_date': '2026-10-%02d 08:00:00' % (1 + int(name_suffix)),
            'car_request_urgent': urgent,
        })
        return request

    def _make_vehicle(self, plate, state='available'):
        return self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'license_plate': plate,
            'recruitment_state': state, 'project_id': self.project.id,
        })

    # ------------------------------------------------------------------
    def test_queue_is_ordered_by_seniority(self):
        older = self._make_request('1')
        newer = self._make_request('2')
        vehicle = self._make_vehicle('QUE-1')
        queue = self.env['recruitment.request']._match_waiting_car_requests(vehicle)
        self.assertEqual(queue[0], older, 'الطابور لم يرتَّب بالأقدمية')
        self.assertIn(newer, queue)

    def test_urgent_jumps_the_queue(self):
        older = self._make_request('1')
        newer_urgent = self._make_request('2', urgent=True)
        vehicle = self._make_vehicle('QUE-2')
        queue = self.env['recruitment.request']._match_waiting_car_requests(vehicle)
        self.assertEqual(queue[0], newer_urgent,
                         'العاجل لم يتقدّم على الأقدم منه')
        self.assertEqual(queue[1], older)

    def test_only_project_manager_raises_urgency(self):
        """قرار صريح: ترتيب الطابور ليس بيد من ينفّذه."""
        request = self._make_request('3')
        with self.assertRaises(UserError):
            request.with_user(self.fleet_user).action_mark_car_urgent()
        request.with_user(self.pm).action_mark_car_urgent()
        self.assertTrue(request.car_request_urgent)

    def test_freeing_a_vehicle_notifies_the_oldest_request(self):
        """الوصلة التي كانت مفقودة: تحرّر مركبة ↔ طلب منتظر."""
        request = self._make_request('4')
        vehicle = self._make_vehicle('QUE-3', state='assigned')
        before = len(request.activity_ids)
        vehicle.write({'recruitment_state': 'available'})
        self.assertGreater(len(request.activity_ids), before,
                           'تحرّر المركبة لم ينبّه الطلب المنتظر')

    def test_vehicle_of_other_project_does_not_notify(self):
        request = self._make_request('5')
        other_project = self.env['project.project'].create({'name': 'منصة أخرى'})
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'license_plate': 'QUE-4',
            'recruitment_state': 'assigned', 'project_id': other_project.id,
        })
        before = len(request.activity_ids)
        vehicle.write({'recruitment_state': 'available'})
        self.assertEqual(len(request.activity_ids), before,
                         'نُبِّه طلب بمركبة لا تخص منصته')

    def test_receive_without_vehicle_puts_request_in_queue(self):
        request = self.env['recruitment.request'].create({
            'employee_name': 'مندوب الانتظار',
            'identification_id': '2000000099', 'mobile': '0500000991',
            'email': 'queue99@example.com',
            'project_id': self.project.id,
        })
        request.write({'car_requested': True, 'car_request_state': 'requested',
                       'car_request_date': '2026-10-01 08:00:00'})
        # كل مركبة متاحة تُحجب: المركبة بلا منصة تصلح لأي طلب كذلك،
        # فحجب منصة واحدة لا يحاكي "لا مركبة متاحة".
        self.env['fleet.vehicle'].search([
            ('recruitment_state', '=', 'available')]).write(
                {'recruitment_state': 'assigned'})
        request.with_user(self.fleet_user).action_fleet_receive()
        self.assertEqual(request.car_request_state, 'waiting',
                         'الطلب بلا مركبة لم يدخل الطابور')

    def test_receive_with_vehicle_leaves_the_queue(self):
        request = self.env['recruitment.request'].create({
            'employee_name': 'مندوب الخروج من الطابور',
            'identification_id': '2000000098', 'mobile': '0500000981',
            'email': 'queue98@example.com',
            'project_id': self.project.id,
        })
        request.write({'car_requested': True, 'car_request_state': 'waiting',
                       'car_request_date': '2026-10-01 08:00:00'})
        self._make_vehicle('QUE-5')
        request.with_user(self.fleet_user).action_fleet_receive()
        self.assertEqual(request.car_request_state, 'received',
                         'الطلب لم يخرج من الطابور رغم توفر مركبة')
