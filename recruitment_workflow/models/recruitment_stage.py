# -*- coding: utf-8 -*-
from odoo import models, fields, api


class RecruitmentStage(models.Model):
    _name = 'recruitment.stage'
    _description = 'مرحلة طلب التوظيف'
    _order = 'sequence, id'

    name = fields.Char(string='اسم المرحلة', required=True, translate=True)
    code = fields.Char(
        string='الرمز',
        required=True,
        help='رمز فني فريد يستخدمه النظام للتحكم في المنطق. مثال: new, project_review, payment ...',
    )
    sequence = fields.Integer(string='الترتيب', default=10)
    fold = fields.Boolean(
        string='مطوي في Kanban',
        help='يتم طي العمود في عرض كانبان افتراضياً.',
    )
    is_closing_stage = fields.Boolean(
        string='مرحلة نهائية',
        help='تشير إلى أن الطلب اكتمل (تم مباشرة العمل).',
    )

    # القواعد الإجبارية للانتقال من هذه المرحلة
    require_attachments = fields.Boolean(
        string='تتطلب اكتمال المرفقات',
        help='لا يمكن الانتقال للمرحلة التالية إلا بعد إرفاق جميع المرفقات الإجبارية.',
    )
    require_car = fields.Boolean(
        string='تتطلب تخصيص سيارة',
        help='لا يمكن الانتقال للمرحلة التالية إلا بعد تخصيص سيارة متاحة من الأسطول.',
    )
    require_project = fields.Boolean(
        string='تتطلب اختيار مشروع/منصة',
        help='لا يمكن الانتقال للمرحلة التالية إلا بعد تحديد المشروع/المنصة '
             '(مثال: كيتا، هنقرستيشن) التي سيعمل عليها المندوب.',
    )
    require_validation = fields.Boolean(
        string='تتطلب موافقة',
        help='تظهر أزرار الموافقة / الرفض في هذه المرحلة.',
    )

    description = fields.Text(string='الوصف', translate=True)
    active = fields.Boolean(string='نشط', default=True)

    _sql_constraints = [
        (
            'code_uniq',
            'unique(code)',
            'رمز المرحلة يجب أن يكون فريداً - يوجد مرحلة أخرى بنفس الرمز.',
        ),
    ]
