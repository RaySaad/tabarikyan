# -*- coding: utf-8 -*-
from odoo import models, fields, api


class RecruitmentAttachmentType(models.Model):
    _name = 'recruitment.attachment.type'
    _description = 'نوع المرفق المطلوب في طلب التوظيف'
    _order = 'sequence, id'

    name = fields.Char(string='اسم المرفق', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    required = fields.Boolean(
        string='إجباري',
        default=True,
        help='إذا كان إجبارياً، يجب رفع هذا المرفق قبل الانتقال للمرحلة التالية.',
    )
    description = fields.Text(string='ملاحظات', translate=True)
    active = fields.Boolean(string='نشط', default=True)


class RecruitmentRequestAttachment(models.Model):
    _name = 'recruitment.request.attachment'
    _description = 'مرفق طلب التوظيف'
    _order = 'sequence, id'

    request_id = fields.Many2one(
        'recruitment.request',
        string='طلب التوظيف',
        required=True,
        ondelete='cascade',
        index=True,
    )
    attachment_type_id = fields.Many2one(
        'recruitment.attachment.type',
        string='نوع المرفق',
        required=True,
    )
    # store=False صراحة: هذا الحقل غير مستخدم في أي فرز/بحث/عرض فعلي (يُستخدم
    # فقط كـ display_name الافتراضي للسجل - _rec_name)، وحقله المصدر
    # (attachment_type_id.name) قابل للترجمة. تخزينه (store=True) مع كونه
    # مرتبطاً (related) بحقل مترجَم كان يسبب تحذير "لن يُحسَب صحيحاً في كل
    # اللغات"، وأسوأ من ذلك: أي تعديل لاحق على translate كان يترك عمود
    # قاعدة البيانات بنوع (jsonb) مغايراً لما يتوقعه الكود (varchar) دون
    # تحويل تلقائي عند الترقية - يسبب فشل أي كتابة تلمس هذا الحقل. عدم
    # تخزينه يُنهي المشكلتين من جذرهما: لا عمود = لا تعارض أنواع ممكن.
    name = fields.Char(
        string='المرفق',
        related='attachment_type_id.name',
        store=False,
        readonly=True,
    )
    sequence = fields.Integer(string='الترتيب', default=10)
    required = fields.Boolean(
        string='إجباري',
        related='attachment_type_id.required',
        store=True,
        readonly=True,
    )
    # حقل ثنائي بسيط (attachment=True يخزّن الملف في ir.attachment تلقائياً)
    file = fields.Binary(string='الملف', attachment=True)
    file_name = fields.Char(string='اسم الملف')
    # غير مخزّن لتفادي مشاكل إعادة الحساب عند رفع الملفات في القوائم
    is_uploaded = fields.Boolean(
        string='تم الرفع',
        compute='_compute_is_uploaded',
    )

    @api.depends('file')
    def _compute_is_uploaded(self):
        for rec in self:
            rec.is_uploaded = bool(rec.file)
