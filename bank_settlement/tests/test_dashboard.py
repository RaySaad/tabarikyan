# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSettlementDashboard(TransactionCase):
    """اختبارات لوحة مؤشرات السداد البنكي (Bank Settlement Dashboard)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.Dashboard = cls.env['bank.settlement.dashboard']
        cls.Advance = cls.env['bank.settlement.advance']
        cls.GovFee = cls.env['bank.settlement.government.fee']

    def test_dashboard_data_structure(self):
        """التحقق من أن دالة get_dashboard_data تعيد البنية المتوقعة بالكامل."""
        data = self.Dashboard.get_dashboard_data('this_month')
        
        # التأكد من وجود المفاتيح الرئيسية
        expected_keys = {'currency', 'kpis', 'approvals', 'alerts', 'charts', 'recent_transactions', 'projects'}
        self.assertTrue(expected_keys.issubset(set(data.keys())))

        # التحقق من بنية المؤشرات المالية
        kpis = data['kpis']
        self.assertIn('total_settled_amount', kpis)
        self.assertIn('total_settled_count', kpis)
        self.assertIn('advances', kpis)
        self.assertIn('government_fees', kpis)
        self.assertIn('vehicle_transfers', kpis)
        self.assertIn('medical_insurance', kpis)
        self.assertIn('representative_settlements', kpis)

        # التحقق من بنية مركز الموافقات
        approvals = data['approvals']
        self.assertIn('adv_wait_pm', approvals)
        self.assertIn('adv_wait_gm', approvals)
        self.assertIn('adv_appr_unpaid', approvals)
        self.assertIn('gov_under_review', approvals)

        # التحقق من الرسوم البيانية
        charts = data['charts']
        self.assertIn('platform', charts)
        self.assertIn('category', charts)
        self.assertIn('monthly_trend', charts)
        self.assertIn('top_gov_fees', charts)
        self.assertIn('top_vehicle_types', charts)

    def test_periods_date_ranges(self):
        """التحقق من صحة حساب الفترات الزمنية المختلفة."""
        for period in ['today', 'this_week', 'this_month', 'last_month', 'this_year', 'all']:
            data = self.Dashboard.get_dashboard_data(period)
            self.assertIsInstance(data['kpis']['total_settled_amount'], (int, float))

    def test_post_due_prepaid_no_lines(self):
        """التحقق من عدم حدوث أخطاء عند استدعاء ترحيل الاستحقاقات في حال عدم وجود أسطر."""
        res = self.Dashboard.action_post_all_due_prepaid()
        self.assertIn(res.get('type'), ['ir.actions.client'])

