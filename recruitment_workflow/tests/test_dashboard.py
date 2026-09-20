# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentWorkflowDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env['recruitment.workflow.dashboard']
        cls.company_1 = cls.env.company

        # إنشاء منصة/مشروع
        cls.project_1 = cls.env['project.project'].create({
            'name': 'كيتا - الرياض',
            'company_id': cls.company_1.id,
            'is_recruitment_open': True,
        })

        # مرحلة البداية
        cls.stage_new = cls.env['recruitment.stage'].search([('code', '=', 'new')], limit=1)
        if not cls.stage_new:
            cls.stage_new = cls.env['recruitment.stage'].create({
                'name': 'طلب جديد',
                'code': 'new',
                'sequence': 1,
            })

        cls.stage_started = cls.env['recruitment.stage'].search([('code', '=', 'started')], limit=1)
        if not cls.stage_started:
            cls.stage_started = cls.env['recruitment.stage'].create({
                'name': 'تم مباشرة العمل',
                'code': 'started',
                'sequence': 90,
            })

    def test_01_get_dashboard_data_structure(self):
        """التحقق من بنية البيانات المسترجعة بواسطة get_dashboard_data"""
        data = self.Dashboard.get_dashboard_data(period='this_month')
        self.assertIn('kpis', data)
        self.assertIn('approvals', data)
        self.assertIn('alerts', data)
        self.assertIn('charts', data)
        self.assertIn('recent_requests', data)
        self.assertIn('projects', data)

        kpis = data['kpis']
        self.assertIn('total_requests', kpis)
        self.assertIn('in_progress_count', kpis)
        self.assertIn('started_count', kpis)
        self.assertIn('rejected_count', kpis)
        self.assertIn('success_rate', kpis)
        self.assertIn('active_couriers_count', kpis)
        self.assertIn('fleet_allocation_rate', kpis)

        charts = data['charts']
        self.assertIn('funnel', charts)
        self.assertIn('platform', charts)
        self.assertIn('monthly_trend', charts)
        self.assertIn('compensation', charts)
        self.assertIn('fleet', charts)

    def test_02_kpi_counts_and_platform_filter(self):
        """التحقق من حسابات المؤشرات والفلترة بحسب المنصة"""
        # إنشاء طلب توظيف تجريبي
        req = self.env['recruitment.request'].create({
            'employee_name': 'مندوب اختبار',
            'identification_id': '1098765432',
            'mobile': '0512345678',
            'email': 'test@example.com',
            'project_id': self.project_1.id,
            'stage_id': self.stage_new.id,
            'company_id': self.company_1.id,
        })

        data_all = self.Dashboard.get_dashboard_data(period='all')
        self.assertGreaterEqual(data_all['kpis']['total_requests'], 1)

        # فلترة بنفس المنصة
        data_filtered = self.Dashboard.get_dashboard_data(period='all', project_id=self.project_1.id)
        self.assertGreaterEqual(data_filtered['kpis']['total_requests'], 1)

    def test_03_period_ranges(self):
        """التحقق من حساب تواريخ الفترات الزمنية المختلفة دون أخطاء"""
        for period in ['today', 'this_week', 'this_month', 'last_month', 'this_year', 'all']:
            start, end, prev_start, prev_end = self.Dashboard._get_period_date_range(period)
            if period != 'all':
                self.assertTrue(start <= end, f"Start date must be <= end date for {period}")
                if prev_start and prev_end:
                    self.assertTrue(prev_start <= prev_end, f"Prev start date must be <= prev end date for {period}")
            data = self.Dashboard.get_dashboard_data(period=period)
            self.assertIsInstance(data, dict)

    def test_04_alerts_calculation(self):
        """التحقق من حسابات التنبيهات الذكية (إقامات، سيارات، مرفقات)"""
        data = self.Dashboard.get_dashboard_data(period='all')
        alerts = data['alerts']
        self.assertIn('iqama_expiring_count', alerts)
        self.assertIn('car_shortage_alert', alerts)
        self.assertIn('incomplete_att_count', alerts)
        self.assertIsInstance(alerts['car_shortage_alert'], dict)
        self.assertIn('has_shortage', alerts['car_shortage_alert'])
