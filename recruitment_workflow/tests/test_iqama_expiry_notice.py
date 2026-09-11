# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIqamaExpiryNotice(TransactionCase):
    """تنبيه الموارد البشرية قبل انتهاء إقامة المندوب.

    رقم الإقامة عندنا هو identification_id، وأودو لا تُقرن به تاريخ
    انتهاء إطلاقاً (تواريخها للتأشيرة ورخصة العمل والجواز) - فالحقل
    والتنبيه مضافان هنا."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.company = cls.env.company
        cls.company.iqama_expiration_notice_period = 60
        cls.hr_user = cls.env['res.users'].create({
            'name': 'مسؤول موارد بشرية', 'login': 'test_iqama_hr',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('hr.group_hr_manager').id,
            ])],
        })

    def _employee(self, expiry, responsible=None):
        # hr_responsible_id حقل مطلوب في أودو 19 (NOT NULL على hr_version)
        # فلا يُمرَّر False - تضعه أودو تلقائياً على المستخدم الحالي.
        vals = {
            'name': 'مندوب إقامة', 'company_id': self.company.id,
            'iqama_expiry_date': expiry,
        }
        if responsible:
            vals['hr_responsible_id'] = responsible.id
        return self.env['hr.employee'].create(vals)

    def _activities(self, employee):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'hr.employee'), ('res_id', '=', employee.id)])

    def test_activity_is_created_inside_the_notice_window(self):
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today + timedelta(days=30), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        activities = self._activities(employee)
        self.assertTrue(activities, 'لم يُنشأ نشاط تنبيه')
        self.assertEqual(activities.user_id, self.hr_user,
                         'التنبيه لم يذهب لمسؤول الموارد البشرية')
        self.assertEqual(activities.date_deadline, employee.iqama_expiry_date)

    def test_no_activity_outside_the_window(self):
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today + timedelta(days=200), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.assertFalse(self._activities(employee))

    def test_already_expired_is_still_notified(self):
        """المطابقة التامة في تنبيه أودو لرخصة العمل تُسقط من فات موعده -
        هنا نستخدم "أقل من أو يساوي" فلا يضيع أحد."""
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today - timedelta(days=5), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.assertTrue(self._activities(employee))

    def test_notice_is_not_repeated_daily(self):
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today + timedelta(days=30), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.assertEqual(len(self._activities(employee)), 1,
                         'تكرر التنبيه في نفس نافذة المهلة')

    def test_renewal_reopens_the_notice(self):
        """تجديد الإقامة يُصفّر الراية فيُنبَّه عليها من جديد في موعدها."""
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today + timedelta(days=30), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.assertTrue(employee.iqama_expiry_activity_done)

        employee.iqama_expiry_date = today + timedelta(days=395)
        self.assertFalse(employee.iqama_expiry_activity_done,
                         'الراية لم تُصفَّر بعد التجديد')

    def test_falls_back_when_responsible_is_not_hr(self):
        """hr_responsible_id مطلوب في أودو فتضعه تلقائياً على مُنشئ
        السجل - وقد يكون موظف إدخال بيانات لا علاقة له بتجديد الإقامات،
        ولا يملك حتى فتح تبويب البيانات الشخصية."""
        outsider = self.env['res.users'].create({
            'name': 'موظف إدخال', 'login': 'test_iqama_outsider',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        today = fields.Date.context_today(self.env.user)
        employee = self._employee(today + timedelta(days=10), outsider)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        activities = self._activities(employee)
        self.assertTrue(activities)
        self.assertNotEqual(activities.user_id, outsider,
                            'التنبيه ذهب لمستخدم ليس من الموارد البشرية')
        self.assertTrue(activities.user_id.has_group('hr.group_hr_user'))

    def test_zero_notice_period_disables_it(self):
        today = fields.Date.context_today(self.env.user)
        self.company.iqama_expiration_notice_period = 0
        employee = self._employee(today + timedelta(days=10), self.hr_user)
        self.env['hr.employee']._cron_notify_iqama_expiry()
        self.assertFalse(self._activities(employee))
