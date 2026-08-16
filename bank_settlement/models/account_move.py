# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_bank_settlement_move = fields.Boolean(
        string='قيد سداد بنكي', default=False, copy=False,
        help='يُضبط تلقائياً عند إنشاء القيد من السداد البنكي - يُستخدم '
             'لحصر رؤية "مستخدم/محاسب" السداد البنكي على قيودهم المرتبطة '
             'فقط (انظر ir.rule في security.xml)، دون الحاجة لصلاحية '
             'محاسبية واسعة تكشف بقية قيود الشركة.',
    )
