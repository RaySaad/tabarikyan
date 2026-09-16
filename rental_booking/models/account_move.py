# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    # تُنقل من أمر التأجير عند إنشاء الفاتورة (sale_order._prepare_invoice)
    # وتُطبع على الفاتورة الضريبية المبسطة بدل اسم "عميل نقدي".
    guest_name = fields.Char(string='اسم المستأجر', copy=False, tracking=True)
    guest_id_number = fields.Char(string='رقم هوية المستأجر', copy=False, tracking=True)
    guest_mobile = fields.Char(string='جوال المستأجر', copy=False, tracking=True)
    # حقل مستقل لا "المرجع": أودو تملأ المرجع باسم أمر البيع (S00892 في
    # نموذج العميل)، وتغييره يقلب سلوكاً قائماً بلا داعٍ.
    booking_reference = fields.Char(string='رقم الحجز', copy=False, tracking=True)
