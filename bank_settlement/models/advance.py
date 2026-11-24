# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.recruitment_workflow.models.internal_context import INTERNAL, is_internal
from odoo.addons.recruitment_workflow.models.saudi_iban import (
    normalize_iban, saudi_iban_error,
)


class BankSettlementAdvance(models.Model):
    """السلف — كود REQ/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.advance'
    _description = 'سلفة موظف'
    _inherit = ['bank.settlement.mixin']

    advance_reason_id = fields.Many2one(
        'bank.settlement.advance.reason', string='سبب السلفة',
        required=True, tracking=True,
    )

    # طريقة استلام الموظف للمبلغ - تحويل بنكي (آيبان) أو STC Pay (رقم
    # الجوال المسجَّل بالمحفظة) - حقل التفاصيل المطابق فقط يظهر حسب
    # الاختيار (انظر views/advance_views.xml).
    payment_method = fields.Selection(
        selection=[
            ('bank_transfer', 'تحويل بنكي'),
            ('stc_pay', 'STC Pay'),
        ],
        string='طريقة الدفع', tracking=True,
    )
    # tracking=True هنا مهم تحديداً - وجهة صرف السلفة الفعلية (حساب
    # الموظف/رقمه على المحفظة). كان بلا أي تتبع سابقاً، فأي تعديل عليهما
    # لا يظهر إطلاقاً في سجل المتابعة (من عدّله ومتى والقيمة القديمة) -
    # ثغرة تدقيق حقيقية على حقول تمثّل بالضبط أين تذهب الأموال.
    employee_iban = fields.Char(string='آيبان الموظف', tracking=True)
    stc_number = fields.Char(string='رقم STC Pay', tracking=True)

    # حالة خاصة بالسلف: بانتظار الموافقة (مسؤول المشروع) ← وافق مسؤول
    # المشروع ← تمت الموافقة (المدير العام) ← تم الصرف. موافقة مسؤول
    # المشروع تأتي أولاً، ثم اعتماد المدير العام - نفس التسلسل المعتاد
    # في الشركات.
    #
    # selection_add (وليس استبدالاً كاملاً لـ selection كما كان سابقاً):
    # الاستبدال الكامل كان يصدر تحذيراً من أودو عند كل تحميل للموديول
    # ("selection=... overrides existing selection; use selection_add
    # instead") - ظهر متكرراً بسجلات الإنتاج وتسبَّب بحالة "Warning"
    # (برتقالي) على odoo.sh. selection_add لا يحذف قيم القائمة الأساسية
    # (under_review/confirmed/done) - تبقى "صالحة" تقنياً على مستوى تعريف
    # الحقل، رغم عدم استخدامها إطلاقاً هنا - القيد أدناه (_check_state_
    # values) يمنع فعلياً كتابتها على سلفة، معوّضاً الحماية التي كان
    # التصريح الكامل يوفّرها تلقائياً.
    state = fields.Selection(
        selection_add=[
            ('waiting_approval', 'بانتظار الموافقة'),
            ('pm_approved', 'وافق مسؤول المشروع'),
            ('approved', 'تمت الموافقة'),
            ('paid', 'تم الصرف'),
        ],
        ondelete={
            'waiting_approval': 'cascade',
            'pm_approved': 'cascade',
            'approved': 'cascade',
            'paid': 'cascade',
        },
    )

    # -- الصرف على دفعات --------------------------------------------------
    # كان الصرف حدثاً واحداً لا يتجزأ: ضغطة "تم الصرف" تُنشئ قيداً واحداً
    # بكامل المبلغ وتُقفل السلفة. والواقع أن المعتمد قد يُحوَّل على دفعات
    # (جزء اليوم وجزء لاحقاً، أو جزء مع الراتب وجزء منفصلاً في اليوم
    # نفسه). انظر advance_disbursement.py.
    disbursement_ids = fields.One2many(
        'bank.settlement.advance.disbursement', 'advance_id',
        string='دفعات الصرف',
    )
    disbursed_amount = fields.Monetary(
        string='المصروف', compute='_compute_disbursement_amounts', store=True,
    )
    undisbursed_amount = fields.Monetary(
        string='المتاح للصرف', compute='_compute_disbursement_amounts', store=True,
    )
    is_partially_disbursed = fields.Boolean(
        string='مصروفة جزئياً', compute='_compute_disbursement_amounts', store=True,
    )
    # عدد الدفعات لا "هل هي جزئية": سلفة اكتمل صرفها على دفعتين لم تعد
    # جزئية، ومع ذلك قيودها متعددة ويجب أن يصل إليها المحاسب.
    disbursement_count = fields.Integer(
        string='عدد دفعات الصرف', compute='_compute_disbursement_amounts',
        store=True,
    )

    @api.depends('total_amount', 'disbursement_ids.amount',
                 'disbursement_ids.state')
    def _compute_disbursement_amounts(self):
        for rec in self:
            done = sum(
                line.amount for line in rec.disbursement_ids
                if line.state == 'posted'
            )
            rec.disbursed_amount = done
            rec.undisbursed_amount = (rec.total_amount or 0.0) - done
            rec.is_partially_disbursed = bool(done) and bool(
                rec.undisbursed_amount)
            rec.disbursement_count = len(rec.disbursement_ids.filtered(
                lambda line: line.state == 'posted'))

    def _get_settlement_move_vals(self):
        """يحترم مبلغ الدفعة الجارية بدل كامل مبلغ السلفة.

        الطرفان معاً: القيد يبقى متوازناً، ويحمل ما حُوِّل فعلاً في هذه
        الدفعة لا ما اعتُمد - فتُطابَق كل حوالة بنكية على حدة."""
        vals = super()._get_settlement_move_vals()
        amount = self.env.context.get('bank_settlement_disbursement_amount')
        if amount:
            for command in vals['line_ids']:
                line = command[2]
                if line.get('debit'):
                    line['debit'] = amount
                if line.get('credit'):
                    line['credit'] = amount
        return vals

    def _disburse(self, amount, date=False, reference=False):
        """يصرف دفعة واحدة بقيدها الخاص ويسجّلها سطراً تحت السلفة.

        الدفعة الأولى تمر بالمسار الأصلي (_ensure_settlement_move_posted)
        لتضبط move_id كما كان تماماً - فيبقى كل ما بُني عليه (الإرجاع
        للتصحيح، إلغاء التنفيذ، زر القيد، استثناء كشف الحساب) عاملاً بلا
        تغيير في الحالة الشائعة: صرف كامل بدفعة واحدة."""
        self.ensure_one()
        date = date or self.transfer_date or fields.Date.context_today(self)
        scoped = self.with_context(bank_settlement_disbursement_amount=amount)
        if not self.move_id:
            scoped._ensure_settlement_move_posted()
            move = self.move_id
        else:
            move_vals = scoped._get_settlement_move_vals()
            move_vals['date'] = date
            move = self.env['account.move'].sudo().create(move_vals)
            move.action_post()
        return self.env['bank.settlement.advance.disbursement'].create({
            'advance_id': self.id,
            'date': date,
            'amount': amount,
            'bank_reference': reference or self.bank_reference,
            'move_id': move.id,
        })

    def action_disburse(self, amount, date=False, reference=False):
        """صرف دفعة - يستدعيه معالج "تم الصرف"."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('يجب الموافقة على السلفة أولاً قبل صرفها.'))
        self._check_group(
            'bank_settlement.group_bank_settlement_reviewer',
            'bank_settlement.group_bank_settlement_manager',
        )
        # الدفعة المقدمة تبني جدول استحقاق من كامل المبلغ وقت الصرف،
        # فصرفها على دفعات يجعل الجدول يستهلك ما لم يُصرف بعد.
        if self.is_prepaid:
            raise UserError(_(
                'الدفعة المقدمة تُصرف كاملةً - جدول الاستحقاق يُبنى من '
                'كامل المبلغ وقت الصرف.'))
        currency = self.currency_id or self.company_id.currency_id
        if currency.compare_amounts(amount, 0) <= 0:
            raise UserError(_('مبلغ الصرف يجب أن يكون أكبر من صفر.'))
        if currency.compare_amounts(amount, self.undisbursed_amount) > 0:
            raise UserError(_(
                'المبلغ المطلوب صرفه (%(amount)s) أكبر من المتاح '
                '(%(left)s) - صُرف من هذه السلفة %(done)s من %(total)s.'
            ) % {
                'amount': amount, 'left': self.undisbursed_amount,
                'done': self.disbursed_amount, 'total': self.total_amount,
            })
        self._disburse(amount, date=date, reference=reference)
        if currency.is_zero(self.undisbursed_amount):
            self._write_state({'state': 'paid'})
            self._save_iban_to_employee()
            self.message_post(body=_(
                'اكتمل صرف السلفة: %(total)s.') % {'total': self.total_amount})
        else:
            self.message_post(body=_(
                'صُرفت دفعة بمبلغ %(amount)s - المصروف %(done)s من '
                '%(total)s، والمتبقي للصرف %(left)s.'
            ) % {
                'amount': amount, 'done': self.disbursed_amount,
                'total': self.total_amount, 'left': self.undisbursed_amount,
            })

    def action_open_disbursement_wizard(self):
        """زر "تم الصرف" في الشاشة - يفتح نافذة اختيار كامل/جزئي.

        action_done تبقى كما هي (صرف كامل المتاح) للاستدعاء المباشر
        والاستيراد: التغيير في الشاشة لا في الواجهة البرمجية."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('يجب الموافقة على السلفة أولاً قبل صرفها.'))
        return {
            'name': _('صرف السلفة'),
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.advance.disbursement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    def action_view_disbursements(self):
        self.ensure_one()
        return {
            'name': _('دفعات صرف %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.advance.disbursement',
            'view_mode': 'list,form',
            'domain': [('advance_id', '=', self.id)],
        }

    def action_view_move(self):
        """سلفة صُرفت على دفعات لها قيد لكل دفعة، وmove_id هو الأول
        وحده - ففتحه يُظهر 500 من سلفة 2000 ويوحي بأن الباقي لم يُصرف.
        تُفتح القيود كلها حين تتعدّد."""
        self.ensure_one()
        moves = self.disbursement_ids.filtered(
            lambda line: line.state == 'posted' and line.move_id
        ).mapped('move_id')
        if len(moves) > 1:
            return {
                'name': _('قيود صرف %s') % self.name,
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'list,form',
                'domain': [('id', 'in', moves.ids)],
            }
        return super().action_view_move()

    def _unpost_settlement_move(self):
        """الإرجاع للتصحيح من "تم الصرف" يعيد قيداً واحداً لمسودة - ولا
        معنى له حين تكون السلفة صُرفت على عدة دفعات بعدة قيود: ستبقى
        البقية مرحَّلة بينما السجل يقول إنه عاد للتصحيح."""
        for rec in self:
            posted = rec.disbursement_ids.filtered(lambda d: d.state == 'posted')
            if len(posted) > 1:
                raise UserError(_(
                    'هذه السلفة صُرفت على %(count)s دفعات بقيود منفصلة - '
                    'استخدم "إلغاء التنفيذ وتصحيح" (يعكس كل الدفعات) بدل '
                    '"إرجاع للتصحيح".'
                ) % {'count': len(posted)})
            # دفعة واحدة: يُحذف سطرها ليُعاد إنشاؤه عند الصرف من جديد،
            # تماماً كما كان السلوك قبل الصرف على دفعات.
            posted.with_context(
                bank_settlement_disbursement_internal=True,
            ).write({'state': 'cancel'})
            posted.with_context(
                bank_settlement_disbursement_internal=True).unlink()
        return super()._unpost_settlement_move()

    def action_reverse_and_correct(self, reason=False):
        # القيد الأول يعكسه المِكسِن (move_id)؛ ودفعات الصرف الإضافية لها
        # قيودها الخاصة فتُعكس هنا - وإلا بقي جزء من المال مصروفاً في
        # الدفاتر لسلفة أُلغي تنفيذها.
        extra = self.disbursement_ids.filtered(
            lambda d: d.state == 'posted' and d.move_id != d.advance_id.move_id)
        result = super().action_reverse_and_correct(reason=reason)
        if extra:
            extra._reverse(reason or '')
        self.disbursement_ids.filtered(
            lambda d: d.state == 'posted'
        ).with_context(
            bank_settlement_disbursement_internal=True,
        ).write({'state': 'cancel'})
        return result

    _INVALID_STATES = ('under_review', 'confirmed', 'done')

    @api.constrains('state')
    def _check_state_values(self):
        """يمنع القيم الثلاث الموروثة من bank_settlement_mixin (under_
        review/confirmed/done) - غير مستخدمة إطلاقاً في سلسلة حالات
        السلفة (انظر شرح selection_add أعلاه) لكنها تبقى "صالحة" تقنياً
        على مستوى تعريف الحقل؛ هذا الفحص يمنع فعلياً أي كتابة مباشرة
        لها (RPC مباشر، أو بعد تعديل عبر Odoo Studio) - نفس الحماية
        التي كان الاستبدال الكامل السابق للـ selection يوفّرها تلقائياً
        قبل التحويل لـ selection_add."""
        for rec in self:
            if rec.state in self._INVALID_STATES:
                raise UserError(_(
                    'حالة "%s" غير صالحة للسلفة - سلسلة حالات السلفة '
                    'مختلفة عن بقية شاشات السداد البنكي (بانتظار '
                    'الموافقة/وافق مسؤول المشروع/تمت الموافقة/تم الصرف).'
                ) % dict(rec._fields['state'].selection).get(rec.state, rec.state))

    def _sequence_code(self):
        return 'bank.settlement.advance'

    def _get_locked_fields_after_approval(self):
        return super()._get_locked_fields_after_approval() + [
            'advance_reason_id', 'payment_method', 'employee_iban', 'stc_number',
        ]

    # _get_editable_states غير مُجاوَزة هنا - القيمة الافتراضية بالـ mixin
    # ('draft' فقط) أصبحت مطابقة لما كان خاصاً بالسلف سابقاً (عُمِّم على
    # كل الشاشات لاحقاً - انظر bank_settlement_mixin.py).

    def _get_direct_approval_step(self):
        # سلسلة السلفة: موافقتان منفصلتان (مسؤول المشروع ثم المدير العام)،
        # ويتوقف عند "تمت الموافقة" حيث يُدخل المحاسب بيانات الصرف.
        self.ensure_one()
        return {
            'draft': self.action_submit_review,
            'waiting_approval': self.action_pm_approve,
            'pm_approved': self.action_confirm,
        }.get(self.state)

    def _get_done_state(self):
        # حالة "منفّذ" في السلفة اسمها "paid" (تم الصرف) - بدونها كان
        # زر "إلغاء التنفيذ وتصحيح" لا يظهر على السلف إطلاقاً، وكان
        # الإرجاع من "تم الصرف" لا يُعيد قيدها لمسودة.
        return 'paid'

    def _get_bank_fields_editable_state(self):
        # حالة اعتماد المدير العام في السلفة اسمها "approved" (تمت
        # الموافقة) بدل "confirmed" المستخدَمة في بقية شاشات السداد
        # البنكي - انظر الشرح الكامل في bank_settlement_mixin.py.
        return 'approved'

    def _get_stage_responsible_user(self):
        """السلفة لها سلسلة حالات خاصة (waiting_approval → pm_approved →
        approved → paid) بدل تسلسل الـ mixin الأساسي - وموافقة مسؤول
        المشروع تستهدف الشخص المحدَّد تحديداً (نفس منطق action_pm_approve)
        بدل أول عضو بالمجموعة، إن وُجد."""
        self.ensure_one()
        if self.state == 'waiting_approval':
            # sudo(): project_id حقل "خاص" (Private) من منظور hr.employee
            # (مخصَّص من recruitment_workflow، غير مُدرَج في hr.employee.
            # public) - بلا sudo() هنا يفشل أي مستخدم سداد بنكي عادي (بلا
            # hr.group_hr_user) بمجرد وصول السلفة لهذه المرحلة، رغم أن
            # القراءة داخلية بحتة (تحديد من يُخطَر) ولا تعرض بيانات الموظف
            # الخاصة له مباشرة.
            project_manager = self.employee_id.sudo().project_id.user_id if self.employee_id else False
            return project_manager or self._get_first_group_user(
                'bank_settlement.group_bank_settlement_manager'
            )
        if self.state == 'pm_approved':
            return self._get_first_group_user('bank_settlement.group_bank_settlement_manager')
        if self.state == 'approved':
            return self._get_first_group_user('bank_settlement.group_bank_settlement_reviewer')
        if self.state == 'rejected':
            return self.create_uid
        return self.env['res.users']

    def _get_returnable_stages(self):
        """للسلفة موافقتان منفصلتان (مسؤول المشروع ثم المدير العام)،
        فلها خيار مرحلتين ممكنتين عند التراجع من "تمت الموافقة" (بعكس
        بقية شاشات السداد البنكي التي لها خيار واحد فقط - انظر
        bank_settlement_mixin.py):
        - pm_approved (الأقرب): تراجع عن اعتماد المدير العام فقط، مع
          إبقاء موافقة مسؤول المشروع سارية.
        - waiting_approval (الأبعد): تراجع عن الموافقتين معاً دفعة
          واحدة - يختاره المستخدم صراحة من المعالج إن أراد ذلك.
        ومن "وافق مسؤول المشروع" نفسها، الخيار الوحيد هو التراجع عن
        موافقة مسؤول المشروع."""
        self.ensure_one()
        selection = dict(self._fields['state'].selection)
        # من "تم الصرف" أيضاً: يعود لما قبل اعتماد المدير العام (أو أبعد
        # لما قبل موافقة مسؤول المشروع)، ويعود قيدها لمسودة ليقبل
        # التصحيح - انظر _unpost_settlement_move في الـ mixin.
        if self.state in ('approved', 'paid'):
            return [
                ('pm_approved', selection.get('pm_approved')),
                ('waiting_approval', selection.get('waiting_approval')),
            ]
        if self.state == 'pm_approved':
            return [('waiting_approval', selection.get('waiting_approval'))]
        return []

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('employee_iban'):
                vals['employee_iban'] = normalize_iban(vals['employee_iban'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('employee_iban'):
            vals['employee_iban'] = normalize_iban(vals['employee_iban'])
        return super().write(vals)

    @api.constrains('employee_iban')
    def _check_employee_iban(self):
        for rec in self:
            error = saudi_iban_error(rec.employee_iban)
            if error:
                raise ValidationError(error)

    def _check_payment_details(self):
        """طريقة الدفع وتفصيلها المطابق إلزاميان قبل الإرسال للمراجعة.

        كانا اختياريين تماماً: فتُرسَل السلفة وتُعتمد وتصل للمحاسب دون أن
        يُعرف أين يُحوَّل المبلغ - والحقول تُقفل بعد الإرسال فلا يُكملها
        المحاسب إلا بإرجاع السجل للتصحيح.

        عند الإرسال لا على الحقل نفسه: الإلزام على الحقل يكسر أي سلفة
        مسودة قائمة بلا طريقة دفع عند أول حفظ. ويسري على الاعتماد المباشر
        من الإدارة أيضاً لأنه يمر بنفس الزر - فالتجاوز يتخطى مَن يعتمد لا
        ما يُشترط."""
        for rec in self:
            if not rec.payment_method:
                raise UserError(
                    'يجب تحديد "طريقة الدفع" قبل إرسال السلفة للمراجعة - '
                    'وإلا لا يُعرف أين يُحوَّل المبلغ.'
                )
            if rec.payment_method == 'bank_transfer' and not rec.employee_iban:
                raise UserError('طريقة الدفع "تحويل بنكي" تتطلب إدخال آيبان الموظف.')
            if rec.payment_method == 'stc_pay' and not rec.stc_number:
                raise UserError('طريقة الدفع "STC Pay" تتطلب إدخال رقم STC Pay.')

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('يمكن إرسال السلف في حالة "مسودة" فقط للمراجعة.')
        self._check_amount_positive_before_submit()
        self._check_payment_details()
        self._write_state({'state': 'waiting_approval'})

    def _save_iban_to_employee(self):
        """يحفظ آيبان السلفة في ملف الموظف إن لم يكن له حساب بنكي.

        عند الصرف لا عند الإدخال: فلا يُحفظ آيبان سلفة رُفضت أو صُحِّحت.
        ولا يُستبدل ولا يُضاف لحساب قائم - الحسابات البنكية للموظف تُدار من
        الموارد البشرية، والسلفة لا تتخذ قراراً بتغيير حساب صرف راتبه.
        استثناء واحد: إن كان نفس الآيبان موجوداً على جهة اتصاله دون ربطه
        بالموظف (فجوة قديمة في طلب التوظيف مع أودو 19) يُربط فقط."""
        self.ensure_one()
        if self.payment_method != 'bank_transfer' or not self.employee_iban or not self.employee_id:
            return
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id
        if not partner or 'bank_account_ids' not in employee._fields:
            return
        Bank = self.env['res.partner.bank'].sudo()
        same = Bank.search([
            ('partner_id', '=', partner.id), ('acc_number', '=', self.employee_iban),
        ], limit=1)
        if same:
            if same not in employee.bank_account_ids:
                employee.bank_account_ids = [(4, same.id)]
            return
        if employee.bank_account_ids or Bank.search_count([('partner_id', '=', partner.id)]):
            return
        account = Bank.create({'acc_number': self.employee_iban, 'partner_id': partner.id})
        employee.bank_account_ids = [(4, account.id)]
        employee.message_post(body=(
            'أُضيف الحساب البنكي %s لملف الموظف من السلفة %s عند صرفها.'
            % (self.employee_iban, self.name)
        ))

    def action_pm_approve(self):
        """موافقة مسؤول المشروع - مسؤول مشروع الموظف نفسه تحديداً
        (employee_id.project_id.user_id)، وليس أي عضو آخر في مجموعة
        مسؤولي المشاريع - نفس فلسفة التعيين المحدَّد في recruitment_
        workflow. إن لم يكن لموظف السلفة مشروع/مسؤول معيّن بعد، يُكتفى
        بالتحقق من صلاحية المدير العام كحل احتياطي."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise UserError('يمكن موافقة مسؤول المشروع في حالة "بانتظار الموافقة" فقط.')
            # sudo(): نفس سبب _get_stage_responsible_user أعلاه - القراءة
            # هنا داخلية بحتة لتحديد "من يحق له الضغط"، وليست عرضاً
            # لبيانات الموظف الخاصة لمن يستدعي الدالة - ثغرة حقيقية
            # مكتشفة بالاختبار الفعلي (AccessError كان يمنع مسؤول المشروع
            # الحقيقي نفسه من الموافقة أصلاً).
            project_manager = rec.employee_id.sudo().project_id.user_id if rec.employee_id else False
            # الاعتماد المباشر من الإدارة يتخطى قاعدة "المسؤول تحديداً" -
            # وهي بالضبط ما كان يمنع حتى المدير العام من اعتماد سلفة عاجلة.
            if project_manager and not rec._is_approval_override_active():
                if rec.env.user != project_manager:
                    raise UserError(
                        'هذه الموافقة تتطلب مسؤول مشروع الموظف نفسه تحديداً (%s).'
                        % project_manager.name
                    )
            else:
                rec._check_group('bank_settlement.group_bank_settlement_manager')
        # إعادة موافقة مسؤول المشروع فعلياً (بعد إرجاع محتمل من "تمت
        # الموافقة") تُغلق نافذة التصحيح المؤقتة - انظر returned_for_
        # correction في bank_settlement_mixin.py.
        self._write_state({'state': 'pm_approved', 'returned_for_correction': False})

    def action_confirm(self):
        """الموافقة على السلفة (اعتماد المدير العام) - تأتي بعد موافقة
        مسؤول المشروع، وتقتصر على المدير العام."""
        for rec in self:
            if rec.state != 'pm_approved':
                raise UserError('يمكن اعتماد المدير العام بعد موافقة مسؤول المشروع فقط.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self._write_state({'state': 'approved', 'returned_for_correction': False})

    def action_done(self):
        """صرف كامل المتاح من السلفة - السلوك الأصلي حرفياً حين لا يكون
        صُرف منها شيء بعد (قيد واحد بكامل المبلغ). تبقى كما هي للاستدعاء
        المباشر والاستيراد؛ والشاشة تمر بالمعالج
        (action_open_disbursement_wizard) ليختار المحاسب كاملاً أو
        جزئياً."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError('يجب الموافقة على السلفة أولاً قبل صرفها.')
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
            if rec.is_prepaid:
                # الدفعة المقدمة تحتفظ بمسارها الأصلي كاملاً.
                rec._ensure_settlement_move_posted()
                rec._write_state({'state': 'paid'})
                rec._save_iban_to_employee()
                continue
            rec.action_disburse(rec.undisbursed_amount)

    def action_reject(self, reason=False):
        """تجاوز - حالة "منفّذة" في السلفة اسمها "paid" (تم الصرف) بدل
        "done" المستخدَمة في بقية شاشات السداد البنكي، والقفل المشترك في
        الـ mixin يتحقق من "done" تحديداً فلن يمنع رفض سلفة "تم الصرف"
        فعلياً بدونه."""
        if not reason:
            raise UserError('يجب إدخال سبب الرفض.')
        for rec in self:
            if rec.state in ('paid', 'cancel', 'rejected'):
                raise UserError(
                    'لا يمكن رفض سلفة بحالة "%s".'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
        for rec in self:
            rec.message_post(body='تم رفض السلفة.<br/>السبب: %s' % reason)
        self._write_state({'state': 'rejected', 'rejection_reason': reason, 'active': False})

    _ADVANCE_REASON_MIGRATION_MAP = {
        'salary_advance': 'bank_settlement.advance_reason_salary_advance',
        'emergency': 'bank_settlement.advance_reason_emergency',
    }

    @api.model
    def _migrate_selection_fields_to_many2one(self):
        """يهاجر القيم القديمة (كانت Selection نصي) لحقل "سبب السلفة" -
        انظر نفس الشرح في government_fee._migrate_selection_fields_to_many2one."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'bank_settlement_advance'
            AND column_name = 'advance_reason'
        """)
        if not self.env.cr.fetchone():
            return
        self.env.cr.execute("""
            SELECT id, advance_reason FROM bank_settlement_advance
            WHERE advance_reason_id IS NULL AND advance_reason IS NOT NULL
        """)
        for rec_id, old_value in self.env.cr.fetchall():
            xmlid = self._ADVANCE_REASON_MIGRATION_MAP.get(old_value)
            new_record = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
            if new_record:
                # يتجاوز قفل "لا تعديل بعد الاعتماد" عمداً - هذه هجرة
                # بيانات قديمة موجودة أصلاً (قد تخص سلفاً مُعتمَدة/مصروفة
                # فعلاً)، وليست تعديلاً حقيقياً لقيمة مختلفة.
                self.browse(rec_id).with_context(
                    bank_settlement_skip_approval_lock=INTERNAL,
                ).advance_reason_id = new_record.id
