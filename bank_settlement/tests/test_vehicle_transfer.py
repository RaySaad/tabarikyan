# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVehicleTransfer(TransactionCase):
    """يتحقق من الربط التلقائي بين الموظف وسيارته عند اختياره في "تحويلات
    المركبات" - طلب صريح: قائمة الاختيار كانت مقيَّدة صحيحاً بسيارات
    الموظف (سائقها الحالي/المستقبلي) لكن بلا أي تعبئة تلقائية، فيضطر
    المستخدم لاختيار نفس السيارة الوحيدة المتاحة يدوياً في كل مرة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.VehicleTransfer = cls.env['bank.settlement.vehicle.transfer']
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'ماركة - تحويل مركبة'})
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'موديل - تحويل مركبة', 'brand_id': brand.id,
        })

    def test_onchange_employee_links_current_driver_vehicle(self):
        partner = self.env['res.partner'].create({'name': 'شريك سائق تجريبي'})
        employee = self.env['hr.employee'].create({
            'name': 'موظف - تحويل مركبة', 'work_contact_id': partner.id,
        })
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'driver_id': partner.id,
        })
        transfer = self.VehicleTransfer.new({})

        transfer.employee_id = employee
        transfer._onchange_employee_id_vehicle()

        self.assertEqual(transfer.vehicle_id, vehicle)

    def test_onchange_employee_links_future_driver_vehicle(self):
        partner = self.env['res.partner'].create({'name': 'شريك سائق مستقبلي تجريبي'})
        employee = self.env['hr.employee'].create({
            'name': 'موظف - سائق مستقبلي', 'work_contact_id': partner.id,
        })
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'future_driver_id': partner.id,
        })
        transfer = self.VehicleTransfer.new({})

        transfer.employee_id = employee
        transfer._onchange_employee_id_vehicle()

        self.assertEqual(transfer.vehicle_id, vehicle)

    def test_onchange_employee_without_vehicle_clears_field(self):
        partner = self.env['res.partner'].create({'name': 'شريك بلا سيارة'})
        employee = self.env['hr.employee'].create({
            'name': 'موظف بلا سيارة', 'work_contact_id': partner.id,
        })
        transfer = self.VehicleTransfer.new({})

        transfer.employee_id = employee
        transfer._onchange_employee_id_vehicle()

        self.assertFalse(transfer.vehicle_id)

    def test_onchange_employee_replaces_previous_vehicle_on_change(self):
        """تغيير الموظف يستبدل السيارة السابقة تلقائياً - لا تبقى سيارة
        الموظف الأول عالقة بالخطأ بعد تغيير الاختيار لموظف آخر."""
        partner1 = self.env['res.partner'].create({'name': 'شريك أول'})
        employee1 = self.env['hr.employee'].create({
            'name': 'موظف أول', 'work_contact_id': partner1.id,
        })
        vehicle1 = self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'driver_id': partner1.id,
        })
        employee2 = self.env['hr.employee'].create({'name': 'موظف ثانٍ بلا سيارة'})
        transfer = self.VehicleTransfer.new({})
        transfer.employee_id = employee1
        transfer._onchange_employee_id_vehicle()
        self.assertEqual(transfer.vehicle_id, vehicle1)

        transfer.employee_id = employee2
        transfer._onchange_employee_id_vehicle()

        self.assertFalse(transfer.vehicle_id)

    def test_clearing_employee_clears_vehicle(self):
        partner = self.env['res.partner'].create({'name': 'شريك للمسح'})
        employee = self.env['hr.employee'].create({
            'name': 'موظف للمسح', 'work_contact_id': partner.id,
        })
        self.env['fleet.vehicle'].create({
            'model_id': self.model.id, 'driver_id': partner.id,
        })
        transfer = self.VehicleTransfer.new({})
        transfer.employee_id = employee
        transfer._onchange_employee_id_vehicle()
        self.assertTrue(transfer.vehicle_id)

        transfer.employee_id = False
        transfer._onchange_employee_id_vehicle()

        self.assertFalse(transfer.vehicle_id)
