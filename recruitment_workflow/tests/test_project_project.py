# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectProjectRecruitment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env['project.project']

    def test_public_projects_single_branch_shown_as_is(self):
        """منصة بدون فروع مكررة (اسم عرض فريد) تظهر كما هي."""
        project = self.Project.create({
            'name': 'منصة فريدة', 'is_recruitment_open': True,
        })
        result = self.Project._get_public_recruitment_projects()
        self.assertIn(project, result)

    def test_public_projects_merges_branches_prefers_default(self):
        """فرعان بنفس "الاسم المعروض للمتقدمين" يظهران كخيار واحد فقط -
        يُفضَّل الفرع المحدَّد كافتراضي حتى لو أُنشئ لاحقاً."""
        branch_1 = self.Project.create({
            'name': 'جاهز', 'is_recruitment_open': True,
            'recruitment_display_name': 'جاهز',
        })
        branch_2 = self.Project.create({
            'name': 'جاهز1', 'is_recruitment_open': True,
            'recruitment_display_name': 'جاهز', 'is_recruitment_default': True,
        })

        result = self.Project._get_public_recruitment_projects()

        jahez_results = result.filtered(lambda p: p.recruitment_display_name == 'جاهز')
        self.assertEqual(len(jahez_results), 1)
        self.assertEqual(jahez_results, branch_2)
        self.assertNotIn(branch_1, result)

    def test_public_projects_merges_branches_falls_back_to_oldest(self):
        """بدون أي فرع محدَّد كافتراضي، يُختار الأقدم (أول id) تلقائياً."""
        branch_1 = self.Project.create({
            'name': 'هنقرستيشن', 'is_recruitment_open': True,
            'recruitment_display_name': 'هنقرستيشن',
        })
        self.Project.create({
            'name': 'هنقرستيشن1', 'is_recruitment_open': True,
            'recruitment_display_name': 'هنقرستيشن',
        })

        result = self.Project._get_public_recruitment_projects()

        hs_results = result.filtered(lambda p: p.recruitment_display_name == 'هنقرستيشن')
        self.assertEqual(hs_results, branch_1)

    def test_public_projects_excludes_closed_projects(self):
        """مشروع غير مفعّل للتسجيل العام لا يظهر إطلاقاً."""
        closed_project = self.Project.create({
            'name': 'مشروع داخلي', 'is_recruitment_open': False,
        })
        result = self.Project._get_public_recruitment_projects()
        self.assertNotIn(closed_project, result)
