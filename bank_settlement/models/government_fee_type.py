# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementGovernmentEntity(models.Model):
    """الجهة الحكومية (وزارة الداخلية، قوى...) - قائمة قابلة للتعديل
    والإضافة من المستخدم نفسه (السداد البنكي ← الإعدادات)، بدل قائمة
    ثابتة بالكود لا يقدر أحد غير المطوّر توسيعها."""
    _name = 'bank.settlement.government.entity'
    _description = 'الجهة الحكومية'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'يوجد جهة حكومية أخرى بنفس الاسم بالفعل.'),
    ]


class BankSettlementGovernmentFeeType(models.Model):
    """نوع الرسوم الحكومية (نقل كفالة، تغيير مهنة...) - قائمة قابلة
    للتعديل والإضافة من المستخدم نفسه."""
    _name = 'bank.settlement.government.fee.type'
    _description = 'نوع الرسوم الحكومية'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'يوجد نوع رسوم آخر بنفس الاسم بالفعل.'),
    ]
