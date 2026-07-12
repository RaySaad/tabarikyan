# -*- coding: utf-8 -*-
from odoo import models, fields


class RecruitmentCompensationType(models.Model):
    _name = 'recruitment.compensation.type'
    _description = 'نظام العمل / نظام الأجر للمندوب'
    _order = 'sequence, id'

    name = fields.Char(string='الاسم', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    description = fields.Text(string='ملاحظات', translate=True)
    active = fields.Boolean(string='نشط', default=True)
