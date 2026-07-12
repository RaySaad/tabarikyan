# -*- coding: utf-8 -*-
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _compute_payment_state(self):
        """payment_state حقل محسوب ومخزَّن (compute+store) يُحدَّث داخلياً عبر
        آلية إعادة الحساب التلقائية عند أي تسوية/تسديد فعلي - وليس عبر
        استدعاء write() مباشر، لذا لا يمكن رصد التغيير بموثوقية إلا من هنا
        (تجاوز write() لا يلتقط أغلب حالات تسجيل الدفعات الفعلية)."""
        before = {move.id: move.payment_state for move in self}
        super()._compute_payment_state()
        newly_settled = self.filtered(
            lambda m: before.get(m.id) not in ('paid', 'in_payment')
            and m.payment_state in ('paid', 'in_payment')
        ).exists()
        if newly_settled:
            # عند اكتمال سداد فاتورة رسوم توظيف فعلياً من تطبيق المحاسبة،
            # ننقل طلب التوظيف تلقائياً من مرحلة "تم السداد" للمرحلة التالية
            # دون أي إجراء يدوي إضافي في موديول التوظيف. sudo() لأن المحاسب
            # قد لا يملك كل صلاحيات سير عمل التوظيف، والانتقال هنا نتيجة
            # مباشرة لحدث محاسبي موثّق (سداد فعلي)، وليس تجاوزاً لأي قيد عمل.
            requests = self.env['recruitment.request'].sudo().search([
                ('fee_move_id', 'in', newly_settled.ids),
                ('stage_id.code', '=', 'paid'),
            ])
            for request in requests:
                request.action_next_stage()
