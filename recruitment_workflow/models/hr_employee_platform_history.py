# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformHistory(models.Model):
    _name = 'hr.employee.platform.history'
    _description = 'سجل تاريخ منصات المندوب'
    _inherit = ['recruitment.workflow.analytic.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'project_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='المندوب',
        required=True,
        # ondelete='restrict' وليس 'cascade': unlink() أدناه يمنع حذف سجل
        # تاريخ المنصات نهائياً "حتى لمدير سير العمل" للحفاظ على سجل تدقيق
        # دائم - لكن 'cascade' كان يُبطل هذه الحماية بالكامل من الخلف: حذف
        # الموظف نفسه (hr.employee) كان يمحو كل سجلات تاريخه تلقائياً عبر
        # قيد المفتاح الأجنبي مباشرة في قاعدة البيانات، متجاوزاً unlink()
        # بالكامل (لا يمر بكود بايثون إطلاقاً) - ثغرة حقيقية تسببت بفقدان
        # سجل تدقيق دائم فعلياً عند حذف موظف له عمليات نشطة مرتبطة.
        ondelete='restrict',
        index=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='المشروع / المنصة',
        required=True,
        index=True,
    )
    date_start = fields.Date(string='تاريخ البداية', required=True)
    date_end = fields.Date(
        string='تاريخ النهاية',
        help='يبقى فارغاً طالما المندوب لا يزال يعمل على هذه المنصة حالياً.',
    )
    is_current = fields.Boolean(
        string='الفترة الحالية',
        compute='_compute_is_current',
        store=True,
    )
    note = fields.Char(string='ملاحظة النقل')
    company_id = fields.Many2one(
        'res.company',
        string='الشركة',
        default=lambda self: self.env.company,
    )

    @api.depends('date_end')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.date_end

    def unlink(self):
        # سجل تاريخ المنصات هو المرجع الرسمي الدائم لمن عمل على أي منصة
        # ومتى - لا يوجد مفهوم "مسودة" هنا (كل فترة تمثّل واقعة فعلية منذ
        # إنشائها)، فيُمنع حذفها نهائياً بالكامل (حتى لمدير سير العمل)،
        # بنفس مبدأ recruitment_request.unlink() تماماً - وإلا أمكن محو
        # فترة تاريخية كاملة بلا أي أثر. تصحيح خطأ يجب أن يمر عبر طلب نقل
        # منصة جديد يفتح فترة صحيحة، وليس حذف الفترة الخاطئة.
        raise UserError(_(
            'لا يمكن حذف سجلات تاريخ المنصات نهائياً، للحفاظ على سجل '
            'تدقيق ومراجعة كامل. أنشئ طلب نقل منصة جديداً لتصحيح الفترة '
            'الحالية إن احتجت ذلك.'
        ))
