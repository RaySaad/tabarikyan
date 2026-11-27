# -*- coding: utf-8 -*-
"""اختبارات ربط المندوب بالموظف والمركبة."""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


@tagged('post_install', '-at_install')
class TestDriverLink(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Driver = cls.env['quick.delivery.driver']
        cls.employee = cls.env['hr.employee'].create({
            'name': 'خالد الحربي', 'mobile_phone': '0551110099'})
        cls.brand = cls.env['fleet.vehicle.model.brand'].create(
            {'name': 'تويوتا'})
        cls.model = cls.env['fleet.vehicle.model'].create(
            {'name': 'هايلكس', 'brand_id': cls.brand.id})
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model.id, 'license_plate': 'ABC-1234'})

    # ------------------------------------------------------- الربط
    def test_a_driver_can_point_at_an_employee(self):
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099',
            'employee_id': self.employee.id})
        self.assertEqual(driver.employee_id, self.employee)

    def test_the_employee_form_shows_the_link_back(self):
        """الربط في الاتجاهين: من بطاقة الموظف تصل إلى مندوبه."""
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099',
            'employee_id': self.employee.id})
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.qd_is_driver)
        self.assertEqual(self.employee.qd_driver_id, driver)

    def test_an_employee_without_a_driver_shows_nothing(self):
        """الضابط المقابل: ليس كل موظف مندوباً."""
        other = self.env['hr.employee'].create({'name': 'محاسب'})
        self.assertFalse(other.qd_is_driver)
        self.assertFalse(other.qd_driver_id)

    @mute_logger('odoo.sql_db')
    def test_one_employee_cannot_be_two_drivers(self):
        self.Driver.create({'name': 'خالد', 'phone': '0551110099',
                            'employee_id': self.employee.id})
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Driver.create({'name': 'خالد مرة أخرى',
                                    'phone': '0551110088',
                                    'employee_id': self.employee.id})

    def test_linking_an_archived_employee_is_refused(self):
        """عند الربط: قيدٌ يمنع ربط مندوب عامل بمن أُنهيت خدمته."""
        self.employee.action_archive()
        with self.assertRaises(ValidationError):
            self.Driver.create({'name': 'خالد', 'phone': '0551110099',
                                'employee_id': self.employee.id})

    def test_archiving_the_employee_stops_the_driver(self):
        """الحارس الحقيقي: رجلٌ تُنهى خدمته صباحاً كان يبقى في
        التطبيق يستلم طلبات العملاء وأموالهم ظهراً."""
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099', 'pin': '7391',
            'driver_status': 'online',
            'employee_id': self.employee.id})
        token = driver._qd_open_session()
        self.employee.action_archive()
        driver.invalidate_recordset()
        self.assertFalse(driver.active, 'المندوب ما زال عاملاً')
        self.assertEqual(driver.driver_status, 'offline')
        self.assertFalse(
            self.Driver._qd_driver_from_session(token),
            'جلسته ما زالت تفتح التطبيق')

    def test_a_driver_of_an_archived_employee_is_never_dispatched(self):
        """النتيجة التي تهمّ: لا يصله طلب بعد إنهاء خدمته."""
        self.Driver.with_context(active_test=False).search([]).write(
            {'driver_status': 'offline'})
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099',
            'driver_status': 'online',
            'current_lat': 24.7136, 'current_lng': 46.6753,
            'employee_id': self.employee.id})
        client = self.env['res.partner'].create({
            'name': 'سوبرماركت الجسر', 'is_qcommerce_client': True})
        self.employee.action_archive()

        order = self.env['quick.delivery.order'].create({
            'client_id': client.id, 'merchant_order_id': 'BRIDGE-1',
            'store_name': 'فرع', 'store_lat': 24.71, 'store_lng': 46.67,
            'customer_name': 'عميل', 'customer_phone': '0550000000',
            'customer_lat': 24.72, 'customer_lng': 46.68})
        self.assertFalse(order.driver_id,
                         'أُسند طلب لمندوب موظفه خارج الخدمة')
        self.assertFalse(driver.exists().active)

    def test_a_stopped_driver_raises_no_complaint(self):
        """الضابط المقابل: مندوبٌ أُوقف مع موظفه لا يُشتكى منه."""
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099',
            'employee_id': self.employee.id})
        self.employee.action_archive()
        driver.invalidate_recordset()
        driver.write({'notes': 'انتهت خدمته'})
        self.assertFalse(driver.active)

    # ----------------------------------------------------- المركبة
    def test_a_driver_can_point_at_a_vehicle(self):
        driver = self.Driver.create({
            'name': 'خالد', 'phone': '0551110099',
            'vehicle_id': self.vehicle.id})
        self.assertEqual(driver.vehicle_id, self.vehicle)
        self.vehicle.invalidate_recordset()
        self.assertEqual(self.vehicle.qd_driver_count, 1)
        self.assertIn(driver, self.vehicle.qd_driver_ids)

    def test_the_plate_is_filled_from_the_vehicle(self):
        """يُغني عن كتابة اللوحة مرتين - ومصدرها الأسطول لا الذاكرة."""
        driver = self.Driver.new({'name': 'خالد', 'phone': '0551110099'})
        driver.vehicle_id = self.vehicle
        driver._onchange_vehicle_id()
        self.assertEqual(driver.vehicle_plate, 'ABC-1234')

    def test_the_name_and_phone_come_from_the_employee(self):
        driver = self.Driver.new({})
        driver.employee_id = self.employee
        driver._onchange_employee_id()
        self.assertEqual(driver.name, 'خالد الحربي')
        self.assertEqual(driver.phone, '0551110099')

    def test_an_existing_phone_is_not_overwritten(self):
        """الضابط: الربط يملأ الفارغ ولا يمسّ ما كُتب بقصد."""
        driver = self.Driver.new({'name': 'اسم مقصود',
                                  'phone': '0559999999'})
        driver.employee_id = self.employee
        driver._onchange_employee_id()
        self.assertEqual(driver.name, 'اسم مقصود')
        self.assertEqual(driver.phone, '0559999999')

    # ------------------------------------------------- الاستقلال
    def test_a_driver_without_an_employee_still_works(self):
        """المندوب كيان مستقل: الجسر يربط ولا يُلزم."""
        driver = self.Driver.create({'name': 'متعاون', 'phone': '0551110077'})
        self.assertFalse(driver.employee_id)
        self.assertFalse(driver.vehicle_id)
        self.assertTrue(driver.active)
