# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementMedicalInsuranceType(models.Model):
    """نوع رسوم التأمين الطبي (تأمين طبي، فحص طبي...) - قائمة قابلة
    للتعديل والإضافة من المستخدم نفسه، بدل قائمة ثابتة بالكود."""
    _name = 'bank.settlement.medical.insurance.type'
    _description = 'نوع رسوم التأمين الطبي'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)
