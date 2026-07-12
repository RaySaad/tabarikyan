# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ProjectProject(models.Model):
    _inherit = 'project.project'

    default_job_id = fields.Many2one(
        'hr.job',
        string='الوظيفة الافتراضية (للتوظيف)',
        help='الوظيفة (وبالتالي القسم) التي تُعبَّأ تلقائياً في طلب التوظيف '
             'عند اختيار هذه المنصة كمشروع. اتركها فارغة إن كانت هذه المنصة '
             'تستقبل أكثر من مسمى وظيفي.',
    )

    def _get_default_analytic_plan(self):
        """يحاول إيجاد خطة تحليلية مناسبة لربط حسابات المشاريع بها:
        1) خطة موجودة اسمها يحتوي "Project"/"مشروع"
        2) أي خطة تحليلية أخرى متاحة
        3) إن لم توجد أي خطة إطلاقاً، يُنشئ خطة جديدة باسم "المشاريع"
        """
        Plan = self.env['account.analytic.plan'].sudo()
        plan = Plan.search(['|', ('name', 'ilike', 'project'), ('name', 'ilike', 'مشروع')], limit=1)
        if not plan:
            plan = Plan.search([], limit=1)
        if not plan:
            plan = Plan.create({'name': 'المشاريع'})
        return plan

    def _create_default_analytic_account(self):
        """ينشئ حساب تحليلي بنفس اسم المشروع ويربطه بالحقل الرسمي
        account_id (الموجود أصلاً في project.project).

        ملاحظة تصميم: هذه الدالة لا تُستدعى تلقائياً عند إنشاء أي مشروع في
        النظام (كانت كذلك سابقاً وتم تصحيحها) - موديول التوظيف ليس مسؤولاً
        عن دورة حياة المشاريع العامة. بدلاً من ذلك، تُستدعى فقط من داخل
        موديول التوظيف نفسه، في اللحظة التي يحتاج فيها فعلياً لحساب تحليلي
        على مشروع تم اختياره كمنصة توصيل (انظر recruitment_request.py
        و hr_employee.py).
        """
        AnalyticAccount = self.env['account.analytic.account'].sudo()
        for project in self:
            if project.account_id:
                continue
            vals = {'name': project.name, 'company_id': project.company_id.id}
            if 'plan_id' in AnalyticAccount._fields:
                default_plan = project._get_default_analytic_plan()
                if default_plan:
                    vals['plan_id'] = default_plan.id
            analytic_account = AnalyticAccount.create(vals)
            project.account_id = analytic_account.id

    def action_create_analytic_account(self):
        """إجراء يدوي اختياري (غير مستخدم حالياً في أي واجهة مشروع عامة)،
        متروك متاحاً لو احتجت استدعاءه يدوياً من كود آخر أو من Server Action."""
        self._create_default_analytic_account()
