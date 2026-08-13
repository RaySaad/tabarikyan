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
