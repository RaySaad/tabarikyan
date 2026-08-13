# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementVehicleTransferType(models.Model):
    """نوع تحويل المركبة (نقل ملكية، تسجيل جديد، وقود وزيوت...) - قائمة
    قابلة للتعديل والإضافة من المستخدم نفسه، بدل قائمة ثابتة بالكود."""
    _name = 'bank.settlement.vehicle.transfer.type'
    _description = 'نوع تحويل المركبة'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)
