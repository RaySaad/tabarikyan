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
    # translate=False صراحة: الحقل المصدر (attachment_type_id.name) قابل
    # للترجمة، لكن هذا الحقل نفسه لا يُعرَض للمستخدم لاختيار لغته بشكل
    # مستقل (مجرد نسخة مخزَّنة لعرض/فرز سريع) - وبلا هذا التحديد كان
    # أودو يحذّر أن الحقل المترجَم المخزَّن هذا "لن يُحسَب صحيحاً في كل
    # اللغات" (نفس القيمة تُخزَّن بغض النظر عن لغة من يحفظ السجل).
    name = fields.Char(
        string='المرفق',
        related='attachment_type_id.name',
        store=True,
        readonly=True,
        translate=False,
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
