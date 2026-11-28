# -*- coding: utf-8 -*-
"""اختبارات كشف حساب المندوب وطلب السلفة.

أخطر ما هنا ليس الحساب بل **العزل**: بيانات مالية على مسار عام.
"""
import json

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


class DriverAccountCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Driver = cls.env['quick.delivery.driver']
        cls.Advance = cls.env['bank.settlement.advance']
        cls.reason = cls.env['bank.settlement.advance.reason'].create(
            {'name': 'ظرف طارئ'})
        cls.employee = cls.env['hr.employee'].create(
            {'name': 'خالد المندوب', 'mobile_phone': '0551110099'})
        cls.driver = cls.Driver.create({
            'name': 'خالد', 'phone': '0551110099', 'pin': '7391',
            'employee_id': cls.employee.id})
        cls.loose = cls.Driver.create({
            'name': 'متعاون بلا ملف', 'phone': '0551110077'})


@tagged('post_install', '-at_install')
class TestAdvanceRequest(DriverAccountCommon):
    """المندوب يطلب ولا يعتمد."""

    def test_a_request_enters_the_approval_chain(self):
        advance = self.driver._qd_request_advance(
            amount=500, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        self.assertEqual(advance.employee_id, self.employee)
        self.assertEqual(advance.amount, 500)
        # لا اعتماد هنا: الحالة التالية في سلسلة الموافقات لا آخرها.
        self.assertEqual(advance.state, 'waiting_approval')

    def test_the_request_is_never_approved_by_the_driver(self):
        advance = self.driver._qd_request_advance(
            amount=300, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        self.assertNotIn(advance.state, ('approved', 'paid', 'pm_approved'))

    def test_a_driver_without_an_employee_cannot_request(self):
        with self.assertRaises(UserError):
            self.loose._qd_request_advance(
                amount=100, reason_id=self.reason.id,
                method='stc_pay', detail='0551110077')

    def test_a_zero_or_negative_amount_is_refused(self):
        for bad in (0, -50):
            with self.assertRaises(UserError):
                self.driver._qd_request_advance(
                    amount=bad, reason_id=self.reason.id,
                    method='stc_pay', detail='0551110099')

    def test_a_non_numeric_amount_is_refused(self):
        with self.assertRaises(UserError):
            self.driver._qd_request_advance(
                amount='ألف', reason_id=self.reason.id,
                method='stc_pay', detail='0551110099')

    def test_the_ceiling_is_enforced(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'quick_delivery.advance_max', '1000')
        with self.assertRaises(UserError):
            self.driver._qd_request_advance(
                amount=1500, reason_id=self.reason.id,
                method='stc_pay', detail='0551110099')

    def test_under_the_ceiling_passes(self):
        """الضابط المقابل: الحدّ لم يُغلق الباب."""
        self.env['ir.config_parameter'].sudo().set_param(
            'quick_delivery.advance_max', '1000')
        advance = self.driver._qd_request_advance(
            amount=900, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        self.assertTrue(advance.id)

    def test_only_one_open_request_at_a_time(self):
        self.driver._qd_request_advance(
            amount=200, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        with self.assertRaises(UserError):
            self.driver._qd_request_advance(
                amount=200, reason_id=self.reason.id,
                method='stc_pay', detail='0551110099')

    def test_a_missing_reason_is_refused(self):
        with self.assertRaises(UserError):
            self.driver._qd_request_advance(
                amount=200, reason_id=False,
                method='stc_pay', detail='0551110099')

    def test_missing_payment_details_are_refused(self):
        with self.assertRaises(UserError):
            self.driver._qd_request_advance(
                amount=200, reason_id=self.reason.id,
                method='bank_transfer', detail='')

    def test_the_request_is_marked_as_coming_from_the_app(self):
        """المحاسب يحتاج أن يعرف مصدر الطلب."""
        advance = self.driver._qd_request_advance(
            amount=200, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099', note='راتب متأخر')
        self.assertIn('تطبيق المندوب', advance.notes)
        self.assertIn('راتب متأخر', advance.notes)


@tagged('post_install', '-at_install')
class TestAccountStatement(DriverAccountCommon):

    def test_the_statement_comes_from_the_shared_function(self):
        """رقمان مختلفان لنفس الرصيد أسوأ من لا رقم."""
        summary = self.driver._qd_account_summary()
        official = self.employee.sudo()._get_employee_statement_data()
        self.assertTrue(summary['has_account'])
        self.assertEqual(summary['net_total'], official['net_total'])

    def test_a_driver_without_an_employee_gets_a_clear_reason(self):
        summary = self.loose._qd_account_summary()
        self.assertFalse(summary['has_account'])
        self.assertIn('الموارد البشرية', summary['reason'])

    def test_the_history_shows_his_own_requests(self):
        self.driver._qd_request_advance(
            amount=250, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        history = self.driver._qd_advance_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['amount'], 250)
        self.assertTrue(history[0]['is_open'])

    def test_one_drivers_advances_never_show_on_another(self):
        """العزل: كشف حساب غيره لا يصله بحال."""
        self.driver._qd_request_advance(
            amount=250, reason_id=self.reason.id,
            method='stc_pay', detail='0551110099')
        self.assertFalse(self.loose._qd_advance_history())


@tagged('post_install', '-at_install')
class TestAccountApi(HttpCase):
    """المسار العام يحمل مالاً: العزل هو ما يُختبر."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Driver = cls.env['quick.delivery.driver']
        cls.reason = cls.env['bank.settlement.advance.reason'].create(
            {'name': 'ظرف طارئ'})
        cls.employee_a = cls.env['hr.employee'].create({'name': 'موظف أ'})
        cls.employee_b = cls.env['hr.employee'].create({'name': 'موظف ب'})
        cls.driver_a = cls.Driver.create({
            'name': 'مندوب أ', 'phone': '0552220011', 'pin': '7391',
            'employee_id': cls.employee_a.id})
        cls.driver_b = cls.Driver.create({
            'name': 'مندوب ب', 'phone': '0552220022', 'pin': '7391',
            'employee_id': cls.employee_b.id})
        cls.env.cr.flush()

    def _login(self, phone):
        response = self.url_open(
            '/api/v1/driver/login',
            data=json.dumps({'phone': phone, 'pin': '7391'}).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        return response.json()['token']

    def _post(self, url, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer %s' % token
        return self.url_open(url, data=json.dumps(body or {}).encode('utf-8'),
                             headers=headers)

    def test_the_account_needs_a_session(self):
        response = self._post('/api/v1/driver/account')
        self.assertEqual(response.status_code, 401)

    def test_a_driver_sees_his_own_account(self):
        token = self._login('0552220011')
        payload = self._post('/api/v1/driver/account', token=token).json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['account']['has_account'])

    def test_a_driver_never_sees_another_drivers_requests(self):
        """لا يقبل المسار مُعرّف موظف في جسمه - ولو أُرسل يُهمَل."""
        self.driver_b._qd_request_advance(
            amount=400, reason_id=self.reason.id,
            method='stc_pay', detail='0552220022')
        self.env.cr.flush()
        token = self._login('0552220011')
        payload = self._post(
            '/api/v1/driver/account',
            {'employee_id': self.employee_b.id,
             'driver_id': self.driver_b.id}, token=token).json()
        self.assertFalse(payload['requests'],
                         'وصلت المندوبَ طلباتُ غيره')

    def test_raising_a_request_over_http(self):
        token = self._login('0552220011')
        response = self._post('/api/v1/driver/advance/request', {
            'amount': 350, 'reason_id': self.reason.id,
            'method': 'stc_pay', 'detail': '0552220011'}, token=token)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload['name'])
        self.assertEqual(payload['state'], 'waiting_approval')

    def test_a_bad_request_returns_the_real_reason(self):
        """رسالة السداد البنكي تصل المندوب كما هي."""
        token = self._login('0552220011')
        response = self._post('/api/v1/driver/advance/request', {
            'amount': -5, 'reason_id': self.reason.id,
            'method': 'stc_pay', 'detail': '0552220011'}, token=token)
        self.assertEqual(response.status_code, 400)
        self.assertIn('صفر', response.json()['error'])

    def test_the_created_advance_belongs_to_the_session_owner(self):
        token = self._login('0552220011')
        self._post('/api/v1/driver/advance/request', {
            'amount': 350, 'reason_id': self.reason.id,
            'method': 'stc_pay', 'detail': '0552220011'}, token=token)
        advances = self.env['bank.settlement.advance'].sudo().search(
            [('employee_id', '=', self.employee_a.id)])
        self.assertEqual(len(advances), 1)
        self.assertFalse(self.env['bank.settlement.advance'].sudo()
                         .search_count([('employee_id', '=',
                                         self.employee_b.id)]))
