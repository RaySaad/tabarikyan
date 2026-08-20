# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ProjectProject(models.Model):
    _inherit = 'project.project'

    department_id = fields.Many2one(
        'hr.department',
        string='القسم (للتوظيف)',
        help='القسم الذي يُعبَّأ تلقائياً في طلب التوظيف عند اختيار هذه '
             'المنصة كمشروع - مباشرة، بغض النظر عن الوظيفة الافتراضية. '
             'إن تُرك فارغاً، يُشتق القسم بدلاً منه من قسم "الوظيفة '
             'الافتراضية" أدناه إن وُجدت.',
    )
    default_job_id = fields.Many2one(
        'hr.job',
        string='الوظيفة الافتراضية (للتوظيف)',
        help='الوظيفة (وبالتالي القسم إن لم يُحدَّد أعلاه) التي تُعبَّأ '
             'تلقائياً في طلب التوظيف عند اختيار هذه المنصة كمشروع. اتركها '
             'فارغة إن كانت هذه المنصة تستقبل أكثر من مسمى وظيفي.',
    )
    compensation_type_ids = fields.Many2many(
        'recruitment.compensation.type',
        string='أنظمة العمل المتاحة',
        help='أنظمة العمل/الأجر التي تدعمها هذه المنصة (بالطلبات، بالعمولة، '
             'راتب ثابت...). تحدِّد خيارات حقل "نظام العمل" في طلب التوظيف '
             'عند اختيار هذه المنصة - فلا تظهر إلا الأنظمة المرتبطة بها.',
    )
    is_recruitment_open = fields.Boolean(
        string='متاحة للتسجيل العام على الموقع',
        default=False,
        help='حدِّد هذا الخيار فقط للمنصات التي تريد أن تظهر في القائمة '
             'المنسدلة بنموذج التسجيل العام على الموقع الإلكتروني '
             '(/careers/register). باقي المشاريع في النظام (محاسبة، تقنية '
             'معلومات...) لن تظهر أبداً للزوار العامين.',
    )
    recruitment_display_name = fields.Char(
        string='الاسم المعروض للمتقدمين (اختياري)',
        help='استخدمه لدمج أكثر من فرع/شركة داخلية لنفس المنصة تحت اسم '
             'واحد ظاهر للمتقدمين على الموقع (مثال: "جاهز" و"جاهز1" '
             'كلاهما يظهران للمتقدم كخيار واحد باسم "جاهز" فقط). اتركه '
             'فارغاً لاستخدام اسم المشروع نفسه.',
    )
    is_recruitment_default = fields.Boolean(
        string='الفرع الافتراضي عند تعدد الفروع النشطة',
        default=False,
        help='عند وجود أكثر من فرع نشط (متاح للتسجيل) بنفس "الاسم المعروض '
             'للمتقدمين"، يُختار الفرع المحدَّد هنا كوجهة تلقائية لطلبات '
             'الموقع الجديدة. إن لم يُحدَّد أي فرع كافتراضي، يُختار الأقدم.',
    )
    recruitment_hidden = fields.Boolean(
        string='استبعاد من قائمة التوظيف',
        default=False,
        help='حدِّد هذا الخيار لإخفاء هذا المشروع تحديداً من قائمة اختيار '
             'المنصة في طلب التوظيف (مثال: مشاريع إدارية/داخلية غير متعلقة '
             'بالتوظيف كـ"Internal")، دون التأثير على استخدامه في تطبيق '
             'المشاريع نفسه. لا علاقة له بظهوره على الموقع الإلكتروني.',
    )

    @api.model
    def _get_public_recruitment_projects(self):
        """يعيد فرعاً واحداً فقط (سجل project.project) لكل "اسم معروض
        للمتقدمين" فريد، من بين كل المنصات المتاحة للتسجيل العام حالياً -
        يمنع ظهور نفس المنصة أكثر من مرة في نموذج تسجيل الموقع عندما تكون
        مقسّمة داخلياً لأكثر من فرع/شركة (مثال: جاهز وجاهز1).

        عند تعدد الفروع النشطة لنفس الاسم: يُفضَّل الفرع المحدَّد كـ
        "افتراضي" (is_recruitment_default) إن وُجد، وإلا الأقدم (أول id).
        """
        open_projects = self.search([('is_recruitment_open', '=', True)], order='id')
        by_display_name = {}
        for project in open_projects:
            key = project.recruitment_display_name or project.name
            chosen = by_display_name.get(key)
            if not chosen or (project.is_recruitment_default and not chosen.is_recruitment_default):
                by_display_name[key] = project
        return self.concat(*by_display_name.values()).sorted('name')

    def write(self, vals):
        tracked = {'user_id', 'company_id'} & set(vals.keys())
        res = super().write(vals)
        if tracked:
            self._sync_recruitment_requests_in_progress(tracked)
        return res

    def _sync_recruitment_requests_in_progress(self, tracked_fields):
        """يحدّث "مسؤول المشروع"/"الشركة" على طلبات التوظيف المرتبطة بهذا
        المشروع تلقائياً عند تعديلهما هنا - لكن فقط للطلبات التي لا تزال
        قيد التنفيذ (state == 'in_progress')؛ الطلبات المكتملة أو المرفوضة
        تبقى بالقيمة التي كانت سارية وقت إنجازها فعلياً، كسجل تاريخي.

        sudo() لأن من يملك صلاحية تعديل المشروع (تطبيق Project) قد لا يملك
        بالضرورة صلاحيات موديول التوظيف، والتحديث هنا نتيجة مباشرة لتعديله
        هو للمشروع، وليس تجاوزاً لقيد موافقة.
        """
        Request = self.env['recruitment.request'].sudo()
        for project in self:
            requests = Request.search([
                ('project_id', '=', project.id),
                ('state', '=', 'in_progress'),
            ])
            if not requests:
                continue
            sync_vals = {'project_id': project.id}
            if 'user_id' in tracked_fields:
                sync_vals['project_manager_id'] = project.user_id.id
            if 'company_id' in tracked_fields:
                sync_vals['company_id'] = project.company_id.id
            requests.write(sync_vals)
            for request in requests:
                request.message_post(body=_(
                    'تم تحديث بيانات المشروع تلقائياً (مسؤول المشروع/الشركة) '
                    'بعد تعديلها على المشروع "%s".'
                ) % project.display_name)

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
            # sudo(): من يستدعي هذه الدالة (مثلاً مسؤول العمليات عند نقل
            # مندوب بين منصات) قد لا يملك بالضرورة صلاحية "Project/
            # Administrator" اللازمة للكتابة المباشرة على project.project -
            # وهذا استنتاج داخلي تلقائي، وليس تعديلاً يدوياً للمشروع نفسه.
            project.sudo().account_id = analytic_account.id

    def action_create_analytic_account(self):
        """إجراء يدوي اختياري (غير مستخدم حالياً في أي واجهة مشروع عامة)،
        متروك متاحاً لو احتجت استدعاءه يدوياً من كود آخر أو من Server Action."""
        self._create_default_analytic_account()
