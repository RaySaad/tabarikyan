# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.recruitment_workflow.models.internal_context import INTERNAL


class BankSettlementAdvanceRepayment(models.Model):
    """دفعة واحدة من استرداد سلفة موظف - سداد جزئي أو كلي.

    لم يكن في الموديول أي أثر للاسترداد إطلاقاً: السلفة تنتهي عند "تم
    الصرف" وتبقى ديناً كاملاً في كشف حساب الموظف إلى الأبد، والطريقة
    الوحيدة لتخفيضها كانت قيداً يدوياً على حساب الذمم لا يظهر من شاشة
    السلفة ولا يربطه بها شيء.

    طريقتان مختلفتان جوهرياً:
    - خصم من الراتب: *بلا قيد محاسبي من هنا*. مسير الرواتب يقيّد الخصم
      أصلاً على حساب ذمم الموظفين (211201)، فإنشاء قيد ثانٍ هنا يحتسب
      الخصم مرتين ويُنقص ذمة الموظف ضعف ما استُقطع فعلاً. السطر هنا
      للمتابعة ولحساب المتبقي فقط.
    - نقدي/تحويل بنكي: نقد يدخل فعلاً، فله قيده - مديناً حساب
      المقبوضات المعلقة ودائناً نفس حساب السلفة (الحساب المرتبط) بشريك
      الموظف، أي عكس قيد الصرف حرفياً.
    """
    _name = 'bank.settlement.advance.repayment'
    _description = 'سداد سلفة'
    _order = 'date desc, id desc'
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
        string='تاريخ السداد', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(string='المبلغ المسدَّد', required=True, tracking=True)

    method = fields.Selection(
        selection=[
            ('salary_deduction', 'خصم من الراتب'),
            ('cash', 'نقدي'),
            ('bank_transfer', 'تحويل بنكي'),
        ],
        string='طريقة السداد', required=True, default='salary_deduction',
        tracking=True,
        help='"خصم من الراتب" لا يُنشئ قيداً محاسبياً هنا - مسير الرواتب '
             'يقيّد الخصم أصلاً على حساب ذمم الموظفين، فالقيد الثاني '
             'يحتسبه مرتين. أما النقدي والتحويل البنكي فنقد يدخل فعلاً، '
             'فيُنشأ لهما قيد.',
    )
    journal_id = fields.Many2one(
        'account.journal', string='دفتر اليومية', tracking=True,
        domain="[('company_id', 'parent_of', company_id)]",
        help='الدفتر الذي يُسجَّل فيه قيد الاسترداد - مطلوب للسداد النقدي '
             'والتحويل البنكي فقط.',
    )
    note = fields.Char(string='ملاحظة')

    move_id = fields.Many2one(
        'account.move', string='القيد المحاسبي', readonly=True, copy=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('posted', 'مسجَّل'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )

    @api.depends('advance_id.name', 'date')
    def _compute_name(self):
        for rec in self:
            rec.name = _('سداد سلفة %(advance)s') % {
                'advance': rec.advance_id.name or ''}

    # -- ضوابط -----------------------------------------------------------
    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('مبلغ السداد يجب أن يكون أكبر من صفر.'))

    @api.constrains('amount', 'state', 'advance_id')
    def _check_not_over_repaid(self):
        """لا يتجاوز مجموع المسدَّد مبلغ السلفة.

        قيد صارم لا تحذير: تجاوزه يعني رصيداً دائناً وهمياً على ذمة
        الموظف يظهر في كشف حسابه كأن للشركة ديناً عليه."""
        for rec in self:
            if rec.state != 'posted':
                continue
            advance = rec.advance_id
            if advance.currency_id.compare_amounts(
                    advance.repaid_amount, advance.total_amount) > 0:
                raise ValidationError(_(
                    'مجموع المسدَّد (%(repaid)s) يتجاوز مبلغ السلفة '
                    '(%(total)s). المتبقي قبل هذه الدفعة كان %(left)s.'
                ) % {
                    'repaid': advance.repaid_amount,
                    'total': advance.total_amount,
                    'left': advance.total_amount - advance.repaid_amount + rec.amount,
                })

    @api.constrains('method', 'journal_id')
    def _check_journal_required(self):
        for rec in self:
            if rec.method != 'salary_deduction' and not rec.journal_id:
                raise ValidationError(_(
                    'السداد النقدي/التحويل البنكي يُنشئ قيداً محاسبياً، '
                    'فيلزمه تحديد دفتر اليومية.'))

    def write(self, vals):
        """سطر مسجَّل لا يُعدَّل - له قيد مرحَّل أو دخل في حساب المتبقي.

        التصحيح يمر بالإلغاء (الذي يعكس القيد) ثم تسجيل دفعة صحيحة -
        نفس مبدأ بقية شاشات السداد البنكي."""
        protected = {'amount', 'date', 'method', 'journal_id', 'advance_id'}
        if protected & set(vals) and not self.env.context.get(
                'bank_settlement_repayment_internal'):
            for rec in self:
                if rec.state == 'posted':
                    raise UserError(_(
                        'لا يمكن تعديل دفعة سداد مسجَّلة - ألغِ الدفعة '
                        '(يُعكس قيدها) ثم سجّل دفعة صحيحة.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    'لا يمكن حذف دفعة سداد مسجَّلة - ألغِها بدل ذلك، '
                    'فيبقى أثرها وقيدها العكسي للتدقيق.'))
        return super().unlink()

    # -- التسجيل والإلغاء -------------------------------------------------
    def _check_repayment_group(self):
        self.ensure_one()
        if not (self.env.user.has_group('bank_settlement.group_bank_settlement_reviewer')
                or self.env.user.has_group('bank_settlement.group_bank_settlement_manager')):
            raise UserError(_(
                'تسجيل سداد السلف يقتصر على محاسب السداد البنكي والمدير العام.'))

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('هذه الدفعة مسجَّلة أو ملغاة بالفعل.'))
            rec._check_repayment_group()
            # السداد قبل الصرف لا معنى له: لا دين بعد.
            if rec.advance_id.state != 'paid':
                raise UserError(_(
                    'لا يمكن تسجيل سداد على سلفة لم تُصرف بعد (حالتها: '
                    '%(state)s).'
                ) % {'state': dict(
                    rec.advance_id._fields['state'].selection).get(
                        rec.advance_id.state, rec.advance_id.state)})
            if rec.method != 'salary_deduction':
                rec.move_id = rec._create_repayment_move()
            rec.state = 'posted'
            rec.advance_id.message_post(body=_(
                'سُجّل سداد بمبلغ %(amount)s (%(method)s) بتاريخ %(date)s.'
                '%(move)s'
            ) % {
                'amount': rec.amount,
                'method': dict(rec._fields['method'].selection).get(rec.method),
                'date': rec.date,
                'move': _('<br/>القيد: %s') % rec.move_id.name if rec.move_id else '',
            })

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancel':
                continue
            rec._check_repayment_group()
            if rec.move_id and rec.move_id.sudo().state == 'posted':
                reverse = rec.move_id.sudo()._reverse_moves([{
                    'date': fields.Date.context_today(rec),
                    'ref': _('عكس %s') % rec.move_id.name,
                }], cancel=True)
                reverse.is_bank_settlement_move = True
                rec.advance_id.message_post(body=_(
                    'أُلغيت دفعة سداد بمبلغ %(amount)s - القيد العكسي: '
                    '%(move)s'
                ) % {'amount': rec.amount, 'move': reverse.name})
            elif rec.move_id:
                rec.move_id.sudo().with_context(
                    bank_settlement_internal_move_write=INTERNAL).button_cancel()
            rec.state = 'cancel'

    # -- القيد المحاسبي ---------------------------------------------------
    def _get_repayment_account(self):
        """الطرف الدائن: نفس حساب السلفة تحديداً.

        الاسترداد عكس الصرف، فيجب أن يُقفل *نفس* الحساب الذي حُمّل به
        الموظف - لا حساب ذمم آخر، وإلا بقي رصيد السلفة قائماً وظهر
        دائن مقابل في حساب ثانٍ بلا مقابل."""
        self.ensure_one()
        account = self.advance_id._get_expense_account()
        if not account:
            raise UserError(_(
                'السلفة بلا "حساب مرتبط"، فلا يُعرف أي حساب يُقفله '
                'الاسترداد. حدّده على السلفة أولاً.'))
        return account

    def _create_repayment_move(self):
        self.ensure_one()
        advance = self.advance_id
        credit_account = self._get_repayment_account()
        # المقبوضات المعلقة لا حساب البنك: المبلغ لم يظهر في كشف البنك
        # بعد، وهذا ما تُطابَق به حركة الكشف لاحقاً - نفس منطق الصرف.
        # ومن *دفتر الاسترداد* لا دفتر الصرف: قد يُسترد نقداً ما صُرف
        # تحويلاً بنكياً.
        debit_account = self.journal_id._bank_settlement_outstanding_account(
            inbound=True, company=advance.company_id)
        if not debit_account:
            debit_account = self.journal_id.default_account_id
            self.advance_id.sudo().message_post(body=_(
                'تنبيه: لم يُعثر على حساب "المقبوضات المعلقة" لدفتر '
                '%(journal)s، فقُيِّد الطرف المدين على حساب البنك مباشرة. '
                'لتفعيل المطابقة البنكية حدّد الحساب من: المحاسبة ← '
                'الإعدادات ← حسابات المدفوعات المعلقة.'
            ) % {'journal': self.journal_id.display_name})
        partner_id = advance._get_settlement_partner_id()
        move = self.env['account.move'].sudo().create({
            'journal_id': self.journal_id.id,
            'company_id': advance.company_id.id,
            'is_bank_settlement_move': True,
            'date': self.date,
            'ref': self.name,
            'line_ids': [
                (0, 0, {
                    'name': self.name,
                    'account_id': debit_account.id,
                    'partner_id': partner_id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': self.name,
                    'account_id': credit_account.id,
                    'partner_id': partner_id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        return move.id
