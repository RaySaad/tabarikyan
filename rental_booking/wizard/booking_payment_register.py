# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class RentalBookingPaymentRegister(models.TransientModel):
    """تسجيل دفعة على حجز التأجير - قبل الفاتورة أو بعدها.

    لا نموذج دفعات جديد: تُنشأ دفعة أودو قياسية (account.payment) وتُرحَّل
    فوراً بتاريخها، فتبقى كل آليات المحاسبة (الدفاتر، طرق الدفع،
    المطابقة، التقارير) كما هي بلا تكرار."""
    _name = 'rental.booking.payment.register'
    _description = 'تسجيل دفعة على حجز التأجير'

    order_id = fields.Many2one('sale.order', string='الحجز', required=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    amount_due = fields.Monetary(
        related='order_id.booking_amount_due', string='المتبقي قبل هذه الدفعة')
    payment_date = fields.Date(
        string='تاريخ الدفع', required=True, default=fields.Date.context_today,
        help='تاريخ القبض الفعلي - يُرحَّل القيد به، فيبقى رصيد الصندوق '
             'صحيحاً لحظة بلحظة.',
    )
    amount = fields.Monetary(string='المبلغ', required=True)
    journal_id = fields.Many2one(
        'account.journal', string='طريقة الدفع', required=True,
        # parent_of لا "=": الحجز قد يكون على فرع بينما دفاتر الصندوق
        # والبنك على الشركة الأم - وهو ترتيبكم الفعلي (نفس ما يفعله
        # bank_settlement). المطابقة الصارمة كانت تُفرغ القائمة تماماً.
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', 'parent_of', company_id)]",
    )
    company_id = fields.Many2one(related='order_id.company_id')
    memo = fields.Char(string='البيان')

    @api.model
    def _eligible_journal_domain(self, company):
        """دفاتر الصندوق/البنك الصالحة لتحصيل حجز هذه الشركة - شاملةً
        دفاتر الشركة الأم إن كان الحجز على فرع."""
        return [('type', 'in', ('bank', 'cash')), ('company_id', 'parent_of', company.id)]

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        order = self.env['sale.order'].browse(values.get('order_id'))
        if order and 'amount' in fields_list:
            values['amount'] = max(order.booking_amount_due, 0.0)
        if order and 'journal_id' in fields_list:
            values['journal_id'] = self.env['account.journal'].search(
                self._eligible_journal_domain(order.company_id), limit=1).id
        return values

    def action_register(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError('مبلغ الدفعة يجب أن يكون أكبر من صفر.')
        if not self.order_id.partner_id:
            raise UserError('يجب تحديد العميل على الحجز قبل تسجيل الدفعة.')
        payment = self.env['account.payment'].create({
            # الشركة صراحةً من شركة الحجز - وإلا حسبتها أودو من *دفتر*
            # الدفع: دفاترهم على الشركة الأم والحجز على فرع ("منتجع سحابة
            # سما")، فتخرج الدفعة على شركة وقيدها على أخرى وترفضها أودو
            # ("لا يُسمح بأي تداخل بين الشركات"). وتحديدها هنا يُسكِت
            # الحساب التلقائي أيضاً: شرطه ألا تكون شركة الدفتر من أصول
            # شركة الدفعة - والأم أصلٌ للفرع، فلا يتدخل.
            'company_id': self.order_id.company_id.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.order_id.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'currency_id': self.currency_id.id,
            'memo': self.memo or self.order_id.name,
            'booking_order_id': self.order_id.id,
        })
        payment.action_post()
        # أودو 19 لا تُنشئ قيد الدفعة إطلاقاً إن كان دفتر الصندوق/البنك
        # بلا "حساب المقبوضات المعلّقة" - تُنشأ الدفعة بلا قيد وبلا أي
        # رسالة، فيظن المستخدم أنه قبض والصندوق لا يعلم. نكشفها هنا.
        if not payment.move_id:
            raise UserError(
                'تعذّر إنشاء قيد الدفعة: دفتر "%s" بلا حساب مقبوضات معلّقة. '
                'اضبطه من: المحاسبة ← الإعدادات ← دفاتر اليومية ← %s ← '
                'المدفوعات الواردة.'
                % (self.journal_id.display_name, self.journal_id.display_name)
            )
        # فاتورة الحجز قد تكون صدرت قبل هذه الدفعة - فتُطابَق فوراً.
        self.order_id._reconcile_booking_payments()
        self.order_id.message_post(body=(
            'سُجّلت دفعة بمبلغ %(amount)s بتاريخ %(date)s (%(journal)s).'
            % {'amount': self.amount, 'date': self.payment_date,
               'journal': self.journal_id.display_name}
        ))
        return {'type': 'ir.actions.act_window_close'}
