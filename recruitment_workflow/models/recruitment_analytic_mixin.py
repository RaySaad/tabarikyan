# -*- coding: utf-8 -*-
from odoo import models, fields, api


class RecruitmentAnalyticProjectMixin(models.AbstractModel):
    """مزيج مشترك: يسحب الحساب التحليلي (مركز التكلفة) تلقائياً من حقل
    project_id الموجود على النموذج الوارث، عبر account_id على project.project.

    يُستخدم في كل النماذج التي تحتاج ربط المنصة (المشروع) بحسابها التحليلي:
    recruitment.request, hr.employee, hr.employee.platform.history - بدلاً
    من تكرار نفس الحقل والدالة في كل منها.
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

    # project_id.account_id ضمن الاعتماديات أيضاً - وليس project_id فقط -
    # وإلا يبقى الحساب التحليلي المخزَّن فارغاً للأبد على أي سجل أُنشئ
    # قبل استدعاء project._create_default_analytic_account() (الحالة
    # الشائعة: الحساب التحليلي يُنشأ لحظياً عند أول حاجة فعلية له، بعد
    # إنشاء الطلب/التكلفة بفترة). ثغرة حقيقية اكتُشفت بمراجعة شاملة: كانت
    # فواتير الرسوم/التكاليف تُصدَر بلا أي توزيع تحليلي فعلياً في هذه الحالة.
    @api.depends('project_id', 'project_id.account_id')
    def _compute_analytic_account_id(self):
        for rec in self:
            rec.analytic_account_id = rec.project_id.account_id
