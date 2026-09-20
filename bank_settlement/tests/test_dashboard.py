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

    def test_filter_by_project_id(self):
        """التحقق من تصفية لوحة المؤشرات حسب منصة/مشروع محدد دون أخطاء."""
        project = self.env['project.project'].search([], limit=1)
        if project:
            data = self.Dashboard.get_dashboard_data('all', project_id=project.id)
            self.assertIn('kpis', data)
            self.assertIn('total_settled_amount', data['kpis'])

    def test_multi_company_platform_aggregation(self):
        """التحقق من تجميع تكاليف المنصات عبر الشركات المتعددة وعدم اختفاء المشاريع من الدائرة."""
        comp1 = self.env.company
        comp2 = self.env['res.company'].create({'name': 'شركة فرعية تجريبية'})

        reason = self.env['bank.settlement.advance.reason'].create({'name': 'سبب تجريبي للمنصات'})

        # إنشاء منصتين بنفس الاسم في الشركتين
        p1_jahez = self.env['project.project'].create({'name': 'جاهز', 'company_id': comp1.id})
        p2_jahez = self.env['project.project'].create({'name': 'جاهز', 'company_id': comp2.id})
        p1_hunger = self.env['project.project'].create({'name': 'هنقرستيشن', 'company_id': comp1.id})

        # إنشاء سلف في الشركتين
        self.Advance.create({
            'name': 'سلفة جاهز شركة 1',
            'company_id': comp1.id,
            'project_id': p1_jahez.id,
            'advance_reason_id': reason.id,
            'amount': 1500.0,
        })._write_state({'state': 'paid'})
        self.Advance.create({
            'name': 'سلفة هنقرستيشن شركة 1',
            'company_id': comp1.id,
            'project_id': p1_hunger.id,
            'advance_reason_id': reason.id,
            'amount': 500.0,
        })._write_state({'state': 'paid'})
        self.Advance.create({
            'name': 'سلفة جاهز شركة 2',
            'company_id': comp2.id,
            'project_id': p2_jahez.id,
            'advance_reason_id': reason.id,
            'amount': 2500.0,
        })._write_state({'state': 'paid'})

        admin = self.env.ref('base.user_admin')
        admin.write({'company_ids': [(4, comp2.id)]})

        # سياق متعدد الشركات
        dash_multi = self.Dashboard.with_context(allowed_company_ids=[comp1.id, comp2.id])
        
        # 1. عند اختيار جميع المنصات: يجب أن تظهر جاهز بمجموع الشركتين (1500 + 2500 = 4000)
        data_all = dash_multi.get_dashboard_data('all')
        plt_labels = data_all['charts']['platform']['labels']
        plt_data = data_all['charts']['platform']['data']
        self.assertIn('جاهز', plt_labels)
        self.assertIn('هنقرستيشن', plt_labels)
        jahez_index = plt_labels.index('جاهز')
        self.assertEqual(plt_data[jahez_index], 4000.0)

        # 2. عند اختيار منصة جاهز تحديداً:
        # - يجب أن يكون إجمالي المؤشرات محتوياً على تكاليف جاهز في كلا الشركتين (4000.0)
        # - ويجب أن تبقى الدائرة تعرض باقي المشاريع (هنقرستيشن) ولا تختفي باقي المشاريع
        data_jahez = dash_multi.get_dashboard_data('all', project_id=p1_jahez.id)
        self.assertEqual(data_jahez['kpis']['total_settled_amount'], 4000.0)
        self.assertIn('هنقرستيشن', data_jahez['charts']['platform']['labels'])
        self.assertIn('جاهز', data_jahez['charts']['platform']['labels'])
