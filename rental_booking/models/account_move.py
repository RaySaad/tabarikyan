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

    def _post(self, soft=True):
        """يطابق دفعات الحجز المسجَّلة *قبل* الفاتورة معها فور ترحيلها.

        المطابقة عند الترحيل لا عند الإنشاء: قيود المسودة لا تُطابَق.
        وبهذا تظهر الفاتورة "مدفوعة" فور إصدارها متى كان النزيل قد سدّد
        عند الحجز - كما في فاتورة العميل النموذجية (دفعتان قبل تاريخ
        الفاتورة ومستحق صفر)."""
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.move_type == 'out_invoice'):
            orders = move.invoice_line_ids.sale_line_ids.order_id
            for order in orders:
                if 'booking_payment_ids' in order._fields and order.booking_payment_ids:
                    order._reconcile_booking_payments(move)
        return posted
