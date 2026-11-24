# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.recruitment_workflow.models.internal_context import INTERNAL


class BankSettlementAdvanceDisbursement(models.Model):
    """دفعة صرف واحدة من سلفة معتمدة - صرف كامل أو جزئي.

    كان الصرف حدثاً واحداً لا يتجزأ: ضغطة "تم الصرف" تُنشئ قيداً واحداً
    بكامل المبلغ وتُقفل السلفة. والواقع أن المبلغ المعتمد قد يُحوَّل على
    دفعات - جزء اليوم وجزء لاحقاً، أو جزء مع الراتب وجزء منفصلاً في
    اليوم نفسه - فلم تكن هناك أي وسيلة لتسجيل ذلك إلا بتزوير المبلغ أو
    إنشاء سلفة ثانية.

    لكل دفعة قيدها الخاص بمبلغها وتاريخها ورقم سدادها، فتُطابَق كل
    حوالة بنكية على حدة. والسلفة تبقى في "تمت الموافقة" حتى يكتمل
    صرفها، فيبقى زر الصرف متاحاً للدفعة التالية."""
    _name = 'bank.settlement.advance.disbursement'
    _description = 'دفعة صرف سلفة'
    _order = 'date, id'
    _inherit = ['mail.thread']

    advance_id = fields.Many2one(
        'bank.settlement.advance', string='السلفة',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(string='المرجع', compute='_compute_name')
    employee_id = fields.Many2one(
        related='advance_id.employee_id', string='الموظف', store=True,
    )
    company_id = fields.Many2one(
        related='advance_id.company_id', string='الشركة', store=True,
    )
    currency_id = fields.Many2one(related='advance_id.currency_id', string='العملة')

    date = fields.Date(
        string='تاريخ التحويل', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(string='المبلغ المصروف', required=True, tracking=True)
    bank_reference = fields.Char(string='رقم السداد البنكي', tracking=True)

    move_id = fields.Many2one(
        'account.move', string='القيد المحاسبي', readonly=True, copy=False,
    )
    state = fields.Selection(
        selection=[
            ('posted', 'مصروفة'),
            ('cancel', 'ملغاة'),
        ],
        string='الحالة', default='posted', required=True, tracking=True, copy=False,
    )

    @api.depends('advance_id.name', 'date')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.advance_id.name or ''

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('مبلغ الصرف يجب أن يكون أكبر من صفر.'))

    @api.constrains('amount', 'state', 'advance_id')
    def _check_not_over_disbursed(self):
        """لا يتجاوز مجموع المصروف المبلغ المعتمد.

        قيد صارم: تجاوزه يعني صرف مال لم يعتمده المدير العام، ويُحمِّل
        ذمة الموظف أكثر مما وافق عليه."""
        for rec in self:
            if rec.state != 'posted':
                continue
            advance = rec.advance_id
            currency = advance.currency_id or advance.company_id.currency_id
            if currency.compare_amounts(
                    advance.disbursed_amount, advance.total_amount) > 0:
                raise ValidationError(_(
                    'مجموع المصروف (%(done)s) يتجاوز المبلغ المعتمد '
                    '(%(total)s). المتاح للصرف قبل هذه الدفعة كان %(left)s.'
                ) % {
                    'done': advance.disbursed_amount,
                    'total': advance.total_amount,
                    'left': advance.total_amount - advance.disbursed_amount + rec.amount,
                })

    def write(self, vals):
        protected = {'amount', 'date', 'advance_id'}
        if protected & set(vals) and not self.env.context.get(
                'bank_settlement_disbursement_internal'):
            for rec in self:
                if rec.state == 'posted':
                    raise UserError(_(
                        'لا يمكن تعديل دفعة صرف لها قيد مرحَّل - استخدم '
                        '"إلغاء التنفيذ وتصحيح" على السلفة.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    'لا يمكن حذف دفعة صرف مرحَّلة - أثرها المحاسبي قائم.'))
        return super().unlink()

    def _reverse(self, reason):
        """يعكس قيد الدفعة ويُلغيها - يُستدعى من "إلغاء التنفيذ وتصحيح"
        على السلفة، فلا تبقى دفعات صرف قائمة لسلفة أُلغي تنفيذها."""
        for rec in self:
            move = rec.move_id.sudo()
            if move and move.state == 'posted':
                reverse = move._reverse_moves([{
                    'date': fields.Date.context_today(rec),
                    'ref': _('عكس %(name)s - %(reason)s') % {
                        'name': move.name, 'reason': reason},
                }], cancel=True)
                reverse.is_bank_settlement_move = True
            elif move:
                move.with_context(
                    bank_settlement_internal_move_write=INTERNAL).button_cancel()
            rec.with_context(
                bank_settlement_disbursement_internal=True,
            ).write({'state': 'cancel'})
