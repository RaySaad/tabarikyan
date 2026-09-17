# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    rental_cash_partner_id = fields.Many2one(
        'res.partner', string='عميل الحجوزات النقدية', ondelete='restrict',
        help='جهة الاتصال الموحّدة لحجوزات الشاليهات المحصّلة نقداً من '
             'النزيل - بدل إنشاء جهة اتصال لكل نزيل.',
    )
    rental_contract_terms = fields.Html(
        string='بنود عقد الإيجار', translate=True, sanitize=False,
        help='نص العقد الذي يُطبع في "عقد الإيجار" ويُرسل للمستأجر - '
             'يُحرَّر من الإعدادات، فلا يحتاج تعديل برمجي عند تغييره.',
    )
    rental_platform_partner_id = fields.Many2one(
        'res.partner', string='عميل منصة الحجز (جاذرن)', ondelete='restrict',
        help='المنصة التي تحصّل من النزيل وتحوّل المبلغ لاحقاً بعد خصم '
             'عمولتها - تُسجَّل الحجوزات المدفوعة عبرها عليها، فتظهر '
             'مستحقاتكم عندها حتى التحويل.',
    )
