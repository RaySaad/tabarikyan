# -*- coding: utf-8 -*-
"""اختبارات معالج تحويل الموظفين إلى مندوبين."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMakeDriver(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Driver = cls.env['quick.delivery.driver']
        cls.Wizard = cls.env['quick.delivery.make.driver']
        cls.client = cls.env['res.partner'].create({
            'name': 'العثيم للمعالج', 'is_qcommerce_client': True})
        cls.ready = cls.env['hr.employee'].create(
            {'name': 'جاهز أول', 'mobile_phone': '0551230001'})
        cls.ready_two = cls.env['hr.employee'].create(
            {'name': 'جاهز ثانٍ', 'mobile_phone': '0551230002'})
        cls.no_phone = cls.env['hr.employee'].create({'name': 'بلا جوال'})

    def _wizard(self, employees, **extra):
        values = {'employee_ids': [(6, 0, employees.ids)]}
        values.update(extra)
        return self.Wizard.create(values)

    # ------------------------------------------------------------------
    def test_the_selection_comes_from_the_employee_list(self):
        """يُفتح من قائمة الموظفين فيأخذ المحدَّدين تلقائياً."""
        wizard = self.Wizard.with_context(
            active_model='hr.employee',
            active_ids=(self.ready | self.ready_two).ids).create({})
        self.assertEqual(wizard.employee_ids, self.ready | self.ready_two)

    def test_several_employees_become_drivers_at_once(self):
        wizard = self._wizard(self.ready | self.ready_two,
                              commission_per_order=11.0)
        wizard.action_create_drivers()
        self.assertEqual(wizard.created_count, 2)
        drivers = self.Driver.search(
            [('employee_id', 'in', (self.ready | self.ready_two).ids)])
        self.assertEqual(len(drivers), 2)
        self.assertEqual(drivers[0].commission_per_order, 11.0)

    def test_the_name_and_phone_come_from_the_file(self):
        """لا يُكتب الاسم والجوال مرتين."""
        self._wizard(self.ready).action_create_drivers()
        driver = self.Driver.search([('employee_id', '=', self.ready.id)])
        self.assertEqual(driver.name, 'جاهز أول')
        self.assertEqual(driver.phone, '0551230001')

    def test_the_merchant_assignment_is_applied(self):
        wizard = self._wizard(self.ready,
                              client_ids=[(6, 0, [self.client.id])])
        wizard.action_create_drivers()
        driver = self.Driver.search([('employee_id', '=', self.ready.id)])
        self.assertEqual(driver.client_ids, self.client)
        self.assertFalse(driver.serves_all_clients)

    def test_an_employee_without_a_phone_is_skipped_with_a_reason(self):
        """التخطّي الصامت يجعلك تبحث عن مندوب لم يُنشأ."""
        wizard = self._wizard(self.ready | self.no_phone)
        wizard.action_create_drivers()
        self.assertEqual(wizard.created_count, 1)
        self.assertIn('بلا جوال', wizard.skipped_text)
        self.assertIn('جوال صالح', wizard.skipped_text)

    def test_an_existing_driver_is_not_duplicated(self):
        self._wizard(self.ready).action_create_drivers()
        again = self._wizard(self.ready)
        with self.assertRaises(UserError):
            again.action_create_drivers()
        self.assertEqual(self.Driver.search_count(
            [('employee_id', '=', self.ready.id)]), 1)

    def test_a_duplicate_phone_is_refused(self):
        self.Driver.create({'name': 'مندوب سابق', 'phone': '0551230001'})
        wizard = self._wizard(self.ready | self.ready_two)
        wizard.action_create_drivers()
        self.assertEqual(wizard.created_count, 1)
        self.assertIn('مسجَّل لمندوب آخر', wizard.skipped_text)

    def test_an_archived_employee_is_skipped(self):
        self.ready.action_archive()
        wizard = self._wizard(self.ready | self.ready_two)
        wizard.action_create_drivers()
        self.assertEqual(wizard.created_count, 1)
        self.assertIn('مؤرشف', wizard.skipped_text)

    # ------------------------------------------------- الأرقام السرية
    def test_no_pins_by_default(self):
        """الأسلم: تُولَّد عند تسليم الجوال لا في ورقة جماعية."""
        wizard = self._wizard(self.ready)
        wizard.action_create_drivers()
        driver = self.Driver.search([('employee_id', '=', self.ready.id)])
        self.assertFalse(driver.has_pin)
        self.assertIn('لم تُولَّد', wizard.result_text)

    def test_pins_are_generated_and_shown_once_on_request(self):
        wizard = self._wizard(self.ready, generate_pins=True)
        wizard.action_create_drivers()
        driver = self.Driver.search([('employee_id', '=', self.ready.id)])
        self.assertTrue(driver.has_pin)
        self.assertIn('مرة واحدة', wizard.result_text)
        # القراءة بعد تفريغ الذاكرة: القيمة تبقى في ذاكرة المعاملة بعد
        # كتابتها، والمقصود أنها لا تُقرأ من قاعدة البيانات.
        driver.invalidate_recordset()
        self.assertEqual(driver.sudo().pin, '',
                         'الرمز يُقرأ من قاعدة البيانات')

    def test_the_pin_sheet_is_short_lived(self):
        """ورقة فيها أرقام عشرين مندوباً لا تبقى ساعةً في القاعدة."""
        self.assertLessEqual(self.Wizard._transient_max_hours, 0.25)
