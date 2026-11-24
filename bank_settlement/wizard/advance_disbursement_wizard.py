# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BankSettlementAdvanceDisbursementWizard(models.TransientModel):
    """نافذة "تم الصرف" - كامل المتاح أو جزء منه.

    كان الزر يصرف كامل المبلغ فوراً بلا سؤال، فلا سبيل لتسجيل تحويل
    جزئي إلا بتغيير المبلغ المعتمد نفسه (وهو مقفول بعد الاعتماد لسبب
    وجيه) أو بإنشاء سلفة ثانية."""
    _name = 'bank.settlement.advance.disbursement.wizard'
    _description = 'معالج صرف السلفة'

    advance_id = fields.Many2one(
        'bank.settlement.advance', string='السلفة', required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(related='advance_id.currency_id')
    total_amount = fields.Monetary(
        related='advance_id.total_amount', string='المبلغ المعتمد')
    disbursed_amount = fields.Monetary(
        related='advance_id.disbursed_amount', string='المصروف سابقاً')
    undisbursed_amount = fields.Monetary(
        related='advance_id.undisbursed_amount', string='المتاح للصرف')

    mode = fields.Selection(
        selection=[
            ('full', 'كامل المتاح'),
            ('partial', 'صرف جزئي'),
        ],
        string='نوع الصرف', required=True, default='full',
    )
    amount = fields.Monetary(
        string='المبلغ المصروف الآن', compute='_compute_amount',
        store=True, readonly=False, required=True,
    )
    date = fields.Date(
        string='تاريخ التحويل', required=True,
        default=fields.Date.context_today,
    )
    bank_reference = fields.Char(string='رقم السداد البنكي')

    @api.depends('mode', 'advance_id')
    def _compute_amount(self):
        """"كامل المتاح" يملأ المبلغ ويقفله - فلا يُترك للمحاسب أن يكتب
        رقماً يخالف ما اختاره."""
        for wizard in self:
            if wizard.mode == 'full':
                wizard.amount = wizard.advance_id.undisbursed_amount
            elif not wizard.amount:
                wizard.amount = 0.0

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        advance = self.env['bank.settlement.advance'].browse(
            values.get('advance_id') or self.env.context.get('default_advance_id'))
        if advance:
            values.setdefault('amount', advance.undisbursed_amount)
            values.setdefault('date', advance.transfer_date or fields.Date.context_today(self))
            values.setdefault('bank_reference', advance.bank_reference)
        return values

    def action_confirm(self):
        self.ensure_one()
        if not self.advance_id:
            raise UserError(_('لا توجد سلفة محدَّدة.'))
        amount = (
            self.advance_id.undisbursed_amount if self.mode == 'full'
            else self.amount
        )
        self.advance_id.action_disburse(
            amount, date=self.date, reference=self.bank_reference)
        return {'type': 'ir.actions.act_window_close'}
