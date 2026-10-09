# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFleetBranchRental(TransactionCase):
    """أجرة الأسطول: الاحتساب من وقائع مسجَّلة لا من إدخال يدوي."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fleet_company = cls.env['res.company'].create({
            'name': 'شركة الأسطول', 'is_fleet_owner': True,
            'fleet_rental_start_date': date(2026, 1, 1)})
        cls.branch = cls.env['res.company'].create({'name': 'فرع التشغيل'})
        cls.other_branch = cls.env['res.company'].create({'name': 'فرع آخر'})
        cls.env.user.company_ids |= (cls.fleet_company | cls.branch | cls.other_branch)
        # تأكيد البلاغ وإغلاقه محصوران بمشرف/مدير الحركة.
        cls.env.user.group_ids |= cls.env.ref(
            'recruitment_workflow.group_recruitment_workflow_fleet_manager')

        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'ماركة الأجرة'})
        model = cls.env['fleet.vehicle.model'].create({
            'name': 'موديل الأجرة', 'brand_id': brand.id})
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'company_id': cls.fleet_company.id,
            'rental_monthly_rate': 3100.0, 'license_plate': 'RNT-1'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'مندوب الأجرة', 'company_id': cls.branch.id})

    def _charge(self, company=None, period=date(2026, 3, 1)):
        return self.env['fleet.branch.rental.charge'].create({
            'company_id': (company or self.branch).id, 'period_date': period})

    def _assign(self, company, date_start, note='اختبار'):
        self.vehicle.sudo()._open_branch_history(company, note, date_start=date_start)

    # ---- الأجرة ----
    def test_full_month_charges_the_whole_rate(self):
        self._assign(self.branch, date(2026, 2, 1))
        charge = self._charge()

        charge.action_generate_lines()

        self.assertEqual(len(charge.line_ids), 1)
        self.assertEqual(charge.line_ids.days, 31, 'مارس 31 يوماً')
        self.assertAlmostEqual(charge.amount_rent, 3100.0, places=2)

    def test_handing_the_vehicle_back_stops_the_rent_that_day(self):
        """تسليم السيارة للأسطول عند حادث أو عطل كبير يوقف الأجرة -
        ولا يُحتسب يوم التسليم على الفرع (هو أول يوم عند الأسطول)."""
        self._assign(self.branch, date(2026, 2, 1))
        self._assign(self.fleet_company, date(2026, 3, 11), 'تسليم للأسطول')
        charge = self._charge()

        charge.action_generate_lines()

        self.assertEqual(charge.line_ids.days, 10, 'من 1 إلى 10 مارس')
        self.assertAlmostEqual(charge.amount_rent, 3100.0 / 31 * 10, places=2)

    def test_a_day_is_never_charged_to_two_branches(self):
        """يوم النقل يخص الفرع الجديد وحده - وإلا تضاعف في كل نقل."""
        self._assign(self.branch, date(2026, 3, 1))
        self._assign(self.other_branch, date(2026, 3, 16))

        first = self._charge(self.branch)
        first.action_generate_lines()
        second = self._charge(self.other_branch)
        second.action_generate_lines()

        self.assertEqual(first.line_ids.days + second.line_ids.days, 31)
        self.assertAlmostEqual(
            first.amount_rent + second.amount_rent, 3100.0, places=2)

    def test_nothing_is_charged_before_the_start_date(self):
        """البيانات القديمة سجلات تدقيق بلا أثر محاسبي (طلب صريح)."""
        self.fleet_company.fleet_rental_start_date = date(2026, 3, 20)
        self._assign(self.branch, date(2026, 1, 1))
        charge = self._charge()

        charge.action_generate_lines()

        self.assertEqual(charge.line_ids.days, 12, 'من 20 إلى 31 مارس')

    def test_a_vehicle_marked_not_chargeable_is_skipped(self):
        self.vehicle.rental_chargeable = False
        self._assign(self.branch, date(2026, 2, 1))
        charge = self._charge()

        charge.action_generate_lines()

        self.assertFalse(charge.line_ids)

    # ---- التلفيات ----
    def _closed_report(self, cost=2000.0, responsibility='employee',
                       close_on=date(2026, 3, 10)):
        report = self.env['fleet.accident.report'].create({
            'vehicle_id': self.vehicle.id, 'employee_id': self.employee.id,
            'accident_date': date(2026, 3, 5), 'responsibility': responsibility,
            'actual_cost': cost})
        report.company_id = self.branch.id
        report.action_confirm()
        report.action_close()
        report.close_date = close_on
        return report

    def test_damage_is_charged_by_the_branch_share(self):
        self._closed_report(cost=2000.0, responsibility='shared')
        charge = self._charge()

        charge.action_generate_lines()

        damage = charge.line_ids.filtered(lambda l: l.line_type == 'damage')
        self.assertEqual(len(damage), 1)
        self.assertAlmostEqual(damage.share_percent, 50.0, places=2)
        self.assertAlmostEqual(charge.amount_damage, 1000.0, places=2)

    def test_third_party_damage_is_not_charged_to_the_branch(self):
        self._closed_report(cost=2000.0, responsibility='third_party')
        charge = self._charge()

        charge.action_generate_lines()

        self.assertFalse(charge.line_ids.filtered(lambda l: l.line_type == 'damage'))

    def test_periodic_maintenance_is_never_charged(self):
        """الصيانة الدورية والأعطال داخل الأجرة على الأسطول - لا يُحمَّل
        إلا ما له بلاغ."""
        service_type = self.env['fleet.service.type'].search([], limit=1)             or self.env['fleet.service.type'].create(
                {'name': 'صيانة دورية اختبار', 'category': 'service'})
        self.env['fleet.vehicle.log.services'].create({
            'vehicle_id': self.vehicle.id, 'amount': 900.0,
            'service_type_id': service_type.id, 'date': date(2026, 3, 7)})
        self._assign(self.branch, date(2026, 3, 1))
        charge = self._charge()

        charge.action_generate_lines()

        self.assertFalse(charge.line_ids.filtered(lambda l: l.line_type == 'damage'))
        self.assertAlmostEqual(charge.amount_total, 3100.0, places=2)

    # ---- الحمايات ----
    def test_two_charges_for_the_same_month_are_refused(self):
        self._charge()
        with self.assertRaises(Exception):
            self._charge()

    def test_the_fleet_company_is_not_charged_rent(self):
        with self.assertRaises(Exception):
            self._charge(self.fleet_company)

    def test_posting_without_accounts_explains_what_is_missing(self):
        self._assign(self.branch, date(2026, 3, 1))
        charge = self._charge()
        charge.action_generate_lines()
        charge.action_confirm()

        with self.assertRaises(UserError):
            charge.action_post()

    # ---- الترحيل المحاسبي ----
    def _configure_accounts(self):
        """حسابات اختبار في الشركتين - في الواقع يحددها المحاسب."""
        def account(company, code, name, acc_type):
            return self.env['account.account'].sudo().create({
                'name': name, 'code': code, 'account_type': acc_type,
                'company_ids': [(6, 0, company.ids)]})

        for company in (self.branch, self.fleet_company):
            journal = self.env['account.journal'].sudo().create({
                'name': 'دفتر التحميل %s' % company.name,
                'code': 'FR%s' % company.id, 'type': 'general',
                'company_id': company.id})
            company.sudo().write({
                'fleet_rental_journal_id': journal.id,
                'fleet_rental_interco_account_id': account(
                    company, 'FR%s1' % company.id, 'جارٍ بين الفروع',
                    'asset_current').id,
                'fleet_rental_expense_account_id': account(
                    company, 'FR%s2' % company.id, 'مصروف أجرة سيارات',
                    'expense').id,
                'fleet_rental_income_account_id': account(
                    company, 'FR%s3' % company.id, 'استرداد تكلفة أسطول',
                    'income').id,
            })

    def test_posting_creates_two_balanced_entries_in_both_companies(self):
        self._configure_accounts()
        self._assign(self.branch, date(2026, 3, 1))
        charge = self._charge()
        charge.action_generate_lines()
        charge.action_confirm()

        charge.action_post()

        self.assertEqual(charge.state, 'posted')
        branch_move = charge.move_branch_id
        fleet_move = charge.move_fleet_id
        self.assertEqual(branch_move.company_id, self.branch)
        self.assertEqual(fleet_move.company_id, self.fleet_company)
        self.assertEqual(branch_move.state, 'posted')
        self.assertEqual(fleet_move.state, 'posted')
        # الفرع: مصروف مدين، جارٍ دائن - والأسطول العكس
        self.assertAlmostEqual(
            sum(branch_move.line_ids.mapped('debit')), charge.amount_total, places=2)
        self.assertAlmostEqual(
            sum(fleet_move.line_ids.mapped('credit')), charge.amount_total, places=2)
        expense = self.branch.fleet_rental_expense_account_id
        income = self.fleet_company.fleet_rental_income_account_id
        self.assertTrue(branch_move.line_ids.filtered(
            lambda l: l.account_id == expense and l.debit > 0),
            'لا سطر مصروف مدين في قيد الفرع')
        self.assertTrue(fleet_move.line_ids.filtered(
            lambda l: l.account_id == income and l.credit > 0),
            'لا سطر إيراد دائن في قيد الأسطول')

    def test_cancelling_a_posted_charge_reverses_both_entries(self):
        self._configure_accounts()
        self._assign(self.branch, date(2026, 3, 1))
        charge = self._charge()
        charge.action_generate_lines()
        charge.action_confirm()
        charge.action_post()

        charge.action_cancel()

        self.assertEqual(charge.state, 'cancel')
        for move in (charge.move_branch_id, charge.move_fleet_id):
            reversal = self.env['account.move'].sudo().search(
                [('reversed_entry_id', '=', move.id)], limit=1)
            self.assertTrue(reversal, 'لم يُعكس القيد %s' % move.name)
            self.assertEqual(reversal.state, 'posted')

    def test_a_posted_charge_cannot_be_deleted_or_reopened(self):
        self._configure_accounts()
        self._assign(self.branch, date(2026, 3, 1))
        charge = self._charge()
        charge.action_generate_lines()
        charge.action_confirm()
        charge.action_post()

        with self.assertRaises(UserError):
            charge.action_reset_draft()
        with self.assertRaises(UserError):
            charge.unlink()

    def test_an_accident_is_never_charged_twice(self):  # noqa: D401
        """البلاغ المحمَّل في شهر لا يعود في الذي يليه."""
        self._configure_accounts()
        self._closed_report(cost=1000.0, responsibility='employee')
        march = self._charge(period=date(2026, 3, 1))
        march.action_generate_lines()
        march.action_confirm()
        march.action_post()

        april = self._charge(period=date(2026, 4, 1))
        april.action_generate_lines()

        self.assertFalse(april.line_ids.filtered(lambda l: l.line_type == 'damage'))

    def test_a_report_held_by_a_draft_charge_is_not_taken_again(self):
        self._closed_report(cost=1000.0, responsibility='employee')
        first = self._charge(period=date(2026, 3, 1))
        first.action_generate_lines()
        self.assertTrue(first.line_ids.filtered(lambda l: l.line_type == 'damage'))

        second = self._charge(self.other_branch, period=date(2026, 3, 1))
        second.action_generate_lines()

        self.assertFalse(second.line_ids.filtered(lambda l: l.line_type == 'damage'))

    def test_cancelling_releases_the_report_for_a_later_charge(self):
        self._closed_report(cost=1000.0, responsibility='employee')
        first = self._charge(period=date(2026, 3, 1))
        first.action_generate_lines()
        first.action_cancel()

        # البلاغ مغلق في مارس، فإعادة تحميله تكون عن مارس نفسه -
        # والتحميل الملغى لا يمنع إنشاء غيره للشهر ذاته.
        again = self._charge(period=date(2026, 3, 1))
        again.action_generate_lines()

        self.assertTrue(again.line_ids.filtered(lambda l: l.line_type == 'damage'),
                        'البلاغ بقي محجوزاً بعد إلغاء تحميله')
