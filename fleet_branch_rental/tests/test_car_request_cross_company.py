# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCarRequestReachesFleetCompany(TransactionCase):
    """طلب سيارة من فرع يجب أن يصل شركة الأسطول.

    الأسطول صار شركة مستقلة، والطلب يخص شركة الفرع - فقاعدة العزل
    بالشركة كانت تُخفيه عن الأسطول تماماً: قائمته تظهر فارغة، فلا
    استلام ولا تفويض ولا عقد تأجير."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.fleet_company = Company.create({
            'name': 'أسطول الطلبات (اختبار)', 'is_fleet_owner': True})
        cls.branch = Company.create({'name': 'فرع الطلبات (اختبار)'})

        model = cls.env['fleet.vehicle.model'].search([], limit=1)
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'license_plate': 'XCO-1',
            'company_id': cls.fleet_company.id,
            'recruitment_state': 'available',
            'rental_monthly_rate': 1700.0,
        })

        cls.request = cls.env['recruitment.request'].create({
            'employee_name': 'مندوب عبر الشركات',
            'identification_id': '2300000001',
            'mobile': '0501110001',
            'email': 'crossco@example.com',
            'company_id': cls.branch.id,
        })
        cls.request.write({
            'car_requested': True,
            'car_request_state': 'requested',
            'car_request_date': '2026-10-01 08:00:00',
        })
        # طلب بلا طلب سيارة - الضابط السالب: لا يجوز أن يراه الأسطول.
        cls.other_request = cls.env['recruitment.request'].create({
            'employee_name': 'مندوب بلا سيارة',
            'identification_id': '2300000002',
            'mobile': '0501110002',
            'email': 'nocar@example.com',
            'company_id': cls.branch.id,
        })

        # مستخدم الأسطول: شركته الوحيدة هي شركة الأسطول.
        cls.fleet_user = cls.env['res.users'].create({
            'name': 'مدير حركة الأسطول', 'login': 'fleet_co_manager',
            'company_id': cls.fleet_company.id,
            'company_ids': [(6, 0, [cls.fleet_company.id])],
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_fleet_manager').id),
            ],
        })

    # ------------------------------------------------------------------
    def test_fleet_company_sees_branch_car_request(self):
        seen = self.env['recruitment.request'].with_user(
            self.fleet_user).search([('id', '=', self.request.id)])
        self.assertTrue(seen, 'طلب السيارة لم يصل شركة الأسطول')

    def test_fleet_company_does_not_see_requests_without_car(self):
        seen = self.env['recruitment.request'].with_user(
            self.fleet_user).search([('id', '=', self.other_request.id)])
        self.assertFalse(
            seen, 'الأسطول يرى طلبات توظيف لا علاقة له بها')

    def test_fleet_reads_vehicle_whose_driver_belongs_to_branch(self):
        """سائق المركبة جهة اتصال أُنشئت في سياق الفرع، فحملت شركته.

        الأسطول مالك المركبة ويفتح بطاقتها، فيسقط بـ"سجلات سرية
        للغاية" على جهة الاتصال - وهو الخطأ الذي أبلغ عنه المستخدم."""
        driver = self.env['res.partner'].create({
            'name': 'سائق المركبة|2300000009', 'company_id': self.branch.id})
        # الضابط: قبل الربط جهة الاتصال محجوبة فعلاً عن الأسطول.
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(
                self.fleet_user).browse(driver.id).read(['name'])

        self.vehicle.sudo().write({'driver_id': driver.id})
        self.assertFalse(
            driver.company_id,
            'ربط السائق بمركبة لم يحرّر جهة اتصاله من ملكية الفرع')
        # وبعد الربط يقرؤها مالك المركبة - وهو ما يقع عند فتح بطاقتها.
        self.assertTrue(self.env['res.partner'].with_user(
            self.fleet_user).browse(driver.id).read(['name']))

    def test_authorize_when_candidate_partner_belongs_to_branch(self):
        """جهة اتصال المندوب تُنشأ بشركة الفرع، ومستخدم الأسطول يقرؤها
        أثناء التفويض - فيسقط بـ"سجلات سرية للغاية"."""
        partner = self.env['res.partner'].create({
            'name': 'سائق الفرع|2300000001', 'company_id': self.branch.id})
        self.request.sudo().candidate_partner_id = partner.id
        request = self.request.with_user(self.fleet_user)
        request.action_fleet_receive()
        request.write({'vehicle_id': self.vehicle.id})
        request.action_fleet_authorize()
        self.assertEqual(request.car_request_state, 'authorized')
        self.assertEqual(self.vehicle.future_driver_id, partner,
                         'لم يُربط المندوب سائقاً مستقبلياً للمركبة')

    def test_fleet_authorizes_and_contract_is_issued(self):
        request = self.request.with_user(self.fleet_user)
        request.action_fleet_receive()
        self.assertEqual(request.car_request_state, 'received')
        request.write({'vehicle_id': self.vehicle.id})
        request.action_fleet_authorize()
        self.assertEqual(request.car_request_state, 'authorized')

        contract = self.env['fleet.rental.contract'].sudo().search([
            ('vehicle_id', '=', self.vehicle.id),
            ('company_id', '=', self.branch.id),
            ('state', '=', 'active'),
        ])
        self.assertTrue(contract, 'لم يصدر عقد التأجير بعد التفويض')
        self.assertEqual(contract.fleet_company_id, self.fleet_company)
        self.assertEqual(contract.monthly_rate, 1700.0,
                         'الأجرة لم تُؤخذ من بطاقة المركبة')
        self.assertEqual(self.request.rental_contract_id, contract,
                         'العقد لم يُربط بطلب التوظيف')
