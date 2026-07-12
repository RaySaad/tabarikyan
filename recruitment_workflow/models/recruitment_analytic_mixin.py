# -*- coding: utf-8 -*-
from odoo import models, fields, api


class RecruitmentAnalyticProjectMixin(models.AbstractModel):
    """مزيج مشترك: يسحب الحساب التحليلي (مركز التكلفة) تلقائياً من حقل
    project_id الموجود على النموذج الوارث، عبر account_id على project.project.

    يُستخدم في كل النماذج التي تحتاج ربط المنصة (المشروع) بحسابها التحليلي:
    recruitment.request, hr.employee, hr.employee.cost,
    hr.employee.platform.history - بدلاً من تكرار نفس الحقل والدالة 4 مرات.
    """
    _name = 'recruitment.workflow.analytic.mixin'
    _description = 'مزيج: حساب تحليلي من المشروع/المنصة'

    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='الحساب التحليلي للمنصة',
        compute='_compute_analytic_account_id',
        store=True,
        help='يُسحب تلقائياً من الحساب التحليلي المرتبط بالمشروع/المنصة المختارة.',
    )

    @api.depends('project_id')
    def _compute_analytic_account_id(self):
        for rec in self:
            rec.analytic_account_id = rec.project_id.account_id
