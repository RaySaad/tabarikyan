# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBranchFleetAccess(TransactionCase):
    """صلاحيات مشرف مركبات الفرع.

    كل اختبار هنا يقابل قراراً صريحاً في التصميم، ولكلٍّ ضابط سالب:
    لا يكفي أن يرى الفرع مركبته، بل يجب ألا يرى مركبة فرع آخر."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.fleet_company = Company.create({
            'name': 'شركة الأسطول (اختبار)', 'is_fleet_owner': True})
        cls.branch_a = Company.create({'name': 'فرع أ (اختبار)'})
        cls.branch_b = Company.create({'name': 'فرع ب (اختبار)'})

        Vehicle = cls.env['fleet.vehicle']
        model = cls.env['fleet.vehicle.model'].search([], limit=1)
        cls.vehicle_a = Vehicle.create({
            'model_id': model.id, 'license_plate': 'TST-A-1',
            'company_id': cls.fleet_company.id, 'rental_monthly_rate': 1500.0,
        })
        cls.vehicle_b = Vehicle.create({
            'model_id': model.id, 'license_plate': 'TST-B-1',
            'company_id': cls.fleet_company.id, 'rental_monthly_rate': 1500.0,
        })

        Contract = cls.env['fleet.rental.contract']
        cls.contract_a = Contract.create({
            'company_id': cls.branch_a.id, 'vehicle_id': cls.vehicle_a.id,
            'monthly_rate': 1500.0, 'date_start': '2026-01-01',
        })
        cls.contract_b = Contract.create({
            'company_id': cls.branch_b.id, 'vehicle_id': cls.vehicle_b.id,
            'monthly_rate': 1500.0, 'date_start': '2026-01-01',
        })

        # base.group_user صراحةً: الدور الداخلي يُمنح في الواجهة عند
        # إنشاء المستخدم، وبدونه يُحجب حتى res.company فلا يعكس
        # الاختبار مستخدماً حقيقياً.
        cls.branch_user = cls.env['res.users'].create({
            'name': 'مشرف فرع أ', 'login': 'branch_a_supervisor',
            'company_id': cls.branch_a.id,
            'company_ids': [(6, 0, [cls.branch_a.id])],
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'fleet_branch_rental.group_fleet_branch_supervisor').id),
            ],
        })
        cls.fleet_user = cls.env['res.users'].create({
            'name': 'مدير الحركة', 'login': 'fleet_manager_test',
            'company_id': cls.fleet_company.id,
            'company_ids': [(6, 0, [cls.fleet_company.id])],
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_fleet_manager').id),
            ],
        })

    # ------------------------------------------------------------------
    def test_branch_sees_only_its_rented_vehicle(self):
        visible = self.env['fleet.vehicle'].with_user(self.branch_user).search([])
        self.assertIn(self.vehicle_a, visible,
                      'الفرع لا يرى المركبة المؤجَّرة له')
        self.assertNotIn(self.vehicle_b, visible,
                         'الفرع يرى مركبة فرع آخر - تسريب')

    def test_branch_creates_fuel_but_cannot_edit(self):
        log = self.env['fleet.fuel.log'].with_user(self.branch_user).create({
            'vehicle_id': self.vehicle_a.id, 'date': '2026-03-05',
            'liters': 40.0, 'amount': 220.0, 'odometer': 12000.0,
        })
        self.assertEqual(log.company_id, self.branch_a,
                         'تكلفة الوقود لم تُنسب إلى الفرع المستأجر')
        with self.assertRaises(AccessError, msg='الفرع عدّل سجلاً بعد إنشائه'):
            log.with_user(self.branch_user).write({'amount': 999.0})

    def test_branch_cannot_write_vehicle_rate(self):
        """الأخطر: لو مُنحت صلاحية أودو للمركبات لخفّض الفرع أجرته."""
        with self.assertRaises(AccessError):
            self.vehicle_a.with_user(self.branch_user).write(
                {'rental_monthly_rate': 1.0})

    def test_fleet_entry_appears_at_branch_immediately(self):
        log = self.env['fleet.fuel.log'].with_user(self.fleet_user).create({
            'vehicle_id': self.vehicle_a.id, 'date': '2026-03-06',
            'liters': 50.0, 'amount': 275.0, 'odometer': 12500.0,
        })
        self.assertEqual(log.company_id, self.branch_a)
        visible = self.env['fleet.fuel.log'].with_user(self.branch_user).search(
            [('id', '=', log.id)])
        self.assertTrue(visible, 'ما أدخله الأسطول لم يظهر عند الفرع')

    def test_branch_does_not_see_other_branch_fuel(self):
        other = self.env['fleet.fuel.log'].with_user(self.fleet_user).create({
            'vehicle_id': self.vehicle_b.id, 'date': '2026-03-07',
            'liters': 30.0, 'amount': 165.0, 'odometer': 8000.0,
        })
        seen = self.env['fleet.fuel.log'].with_user(self.branch_user).search(
            [('id', '=', other.id)])
        self.assertFalse(seen, 'الفرع يرى وقود فرع آخر')

    def test_branch_raises_service_request_and_cannot_accept_it(self):
        request = self.env['fleet.service.request'].with_user(
            self.branch_user).create({
                'vehicle_id': self.vehicle_a.id,
                'request_type': 'breakdown',
                'description': 'صوت من المحرك',
            })
        self.assertEqual(request.company_id, self.branch_a)
        self.assertEqual(request.state, 'new')
        with self.assertRaises(AccessError,
                               msg='الفرع غيّر حالة طلبه بنفسه'):
            request.with_user(self.branch_user).action_accept()
        request.with_user(self.fleet_user).action_accept()
        self.assertEqual(request.state, 'accepted')

    def test_branch_sees_workshop_cost_of_its_vehicle(self):
        """قرار صاحب العمل: الشفافية مطلوبة - الفرع يرى كم كلّفت."""
        service_type = self.env['fleet.service.type'].search([], limit=1)
        log = self.env['fleet.vehicle.log.services'].with_user(
            self.fleet_user).create({
                'vehicle_id': self.vehicle_a.id,
                'service_type_id': service_type.id,
                'date': '2026-03-08', 'amount': 800.0,
            })
        seen = self.env['fleet.vehicle.log.services'].with_user(
            self.branch_user).search([('id', '=', log.id)])
        self.assertTrue(seen, 'الفرع لا يرى تكلفة ورشة مركبته')
