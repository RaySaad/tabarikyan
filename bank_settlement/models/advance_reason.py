# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementAdvanceReason(models.Model):
    """سبب السلفة (سلفة راتب، طارئة...) - قائمة قابلة للتعديل والإضافة
    من المستخدم نفسه، بدل قائمة ثابتة بالكود."""
    _name = 'bank.settlement.advance.reason'
    _description = 'سبب السلفة'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)

    # ملاحظة: _sql_constraints (الصيغة القديمة) لم تعد فعّالة إطلاقاً في
    # هذا الإصدار من Odoo (تحذير صامت عند التحميل: "no longer supported")
    # - القيد كان معطَّلاً بالكامل بلا أي رسالة خطأ واضحة. models.Constraint
    # هي الصيغة الحالية المدعومة فعلياً.
    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد سبب سلفة آخر بنفس الاسم بالفعل.',
    )
