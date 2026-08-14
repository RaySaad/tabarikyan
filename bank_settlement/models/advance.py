# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


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
    employee_iban = fields.Char(string='آيبان الموظف')
    stc_number = fields.Char(string='رقم STC Pay')

    # حالة خاصة بالسلف: بانتظار الموافقة (مسؤول المشروع) ← وافق مسؤول
    # المشروع ← تمت الموافقة (المدير العام) ← تم الصرف. موافقة مسؤول
    # المشروع تأتي أولاً، ثم اعتماد المدير العام - نفس التسلسل المعتاد
    # في الشركات.
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_approval', 'بانتظار الموافقة'),
            ('pm_approved', 'وافق مسؤول المشروع'),
            ('approved', 'تمت الموافقة'),
            ('paid', 'تم الصرف'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.advance'

    def _get_locked_fields_after_approval(self):
        return super()._get_locked_fields_after_approval() + [
            'advance_reason_id', 'payment_method', 'employee_iban', 'stc_number',
        ]

    def _get_editable_states(self):
        # القفل يبدأ فور الإرسال للمراجعة مباشرة (وليس فقط بعد الاعتماد
        # النهائي) - بناءً على طلب صريح.
        return ('draft',)

    def _get_bank_fields_editable_state(self):
        # حالة اعتماد المدير العام في السلفة اسمها "approved" (تمت
        # الموافقة) بدل "confirmed" المستخدَمة في بقية شاشات السداد
        # البنكي - انظر الشرح الكامل في bank_settlement_mixin.py.
        return 'approved'

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('يمكن إرسال السلف في حالة "مسودة" فقط للمراجعة.')
        self.write({'state': 'waiting_approval'})

    def action_pm_approve(self):
        """موافقة مسؤول المشروع - مسؤول مشروع الموظف نفسه تحديداً
        (employee_id.project_id.user_id)، وليس أي عضو آخر في مجموعة
        مسؤولي المشاريع - نفس فلسفة التعيين المحدَّد في recruitment_
        workflow. إن لم يكن لموظف السلفة مشروع/مسؤول معيّن بعد، يُكتفى
        بالتحقق من صلاحية المدير العام كحل احتياطي."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise UserError('يمكن موافقة مسؤول المشروع في حالة "بانتظار الموافقة" فقط.')
            project_manager = rec.employee_id.project_id.user_id if rec.employee_id else False
            if project_manager:
                if rec.env.user != project_manager:
                    raise UserError(
                        'هذه الموافقة تتطلب مسؤول مشروع الموظف نفسه تحديداً (%s).'
                        % project_manager.name
                    )
            else:
                rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'pm_approved'})

    def action_confirm(self):
        """الموافقة على السلفة (اعتماد المدير العام) - تأتي بعد موافقة
        مسؤول المشروع، وتقتصر على المدير العام."""
        for rec in self:
            if rec.state != 'pm_approved':
                raise UserError('يمكن اعتماد المدير العام بعد موافقة مسؤول المشروع فقط.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'approved'})

    def action_done(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError('يجب الموافقة على السلفة أولاً قبل صرفها.')
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
            if not rec.move_id:
                rec.move_id = rec._create_settlement_move()
        self.write({'state': 'paid'})

    def action_reset_draft(self):
        """إعادة لمسودة - تُلغي فعلياً اعتماد المدير العام السابق، فتتطلب
        نفس صلاحيته تحديداً - وليست متاحة لمن أنشأ السلفة فقط."""
        for rec in self:
            if rec.move_id:
                raise UserError(
                    'لا يمكن إعادة هذه السلفة لمسودة - يوجد قيد محاسبي مرتبط '
                    'بها بالفعل (%s). ألغِ/اعكس القيد أولاً من المحاسبة.'
                    % rec.move_id.name
                )
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'draft'})

    def action_cancel(self):
        """إلغاء - متاح للمراجع فما فوق (وليس لمن أنشأ السلفة فقط)."""
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(
                    'لا يمكن إلغاء هذه السلفة - القيد المحاسبي المرتبط بها '
                    'مرحّل بالفعل (%s). ألغِه/اعكسه من المحاسبة أولاً.'
                    % rec.move_id.name
                )
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
        self.write({'state': 'cancel'})

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
                    bank_settlement_skip_approval_lock=True,
                ).advance_reason_id = new_record.id
