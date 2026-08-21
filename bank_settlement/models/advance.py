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
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_approval', 'بانتظار الموافقة'),
            ('pm_approved', 'وافق مسؤول المشروع'),
            ('approved', 'تمت الموافقة'),
            ('paid', 'تم الصرف'),
            ('rejected', 'مرفوضة'),
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

    # _get_editable_states غير مُجاوَزة هنا - القيمة الافتراضية بالـ mixin
    # ('draft' فقط) أصبحت مطابقة لما كان خاصاً بالسلف سابقاً (عُمِّم على
    # كل الشاشات لاحقاً - انظر bank_settlement_mixin.py).

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
        if self.state == 'approved':
            return [
                ('pm_approved', selection.get('pm_approved')),
                ('waiting_approval', selection.get('waiting_approval')),
            ]
        if self.state == 'pm_approved':
            return [('waiting_approval', selection.get('waiting_approval'))]
        return []

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('يمكن إرسال السلف في حالة "مسودة" فقط للمراجعة.')
        self._check_amount_positive_before_submit()
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
            # sudo(): نفس سبب _get_stage_responsible_user أعلاه - القراءة
            # هنا داخلية بحتة لتحديد "من يحق له الضغط"، وليست عرضاً
            # لبيانات الموظف الخاصة لمن يستدعي الدالة - ثغرة حقيقية
            # مكتشفة بالاختبار الفعلي (AccessError كان يمنع مسؤول المشروع
            # الحقيقي نفسه من الموافقة أصلاً).
            project_manager = rec.employee_id.sudo().project_id.user_id if rec.employee_id else False
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
        self.write({'state': 'rejected', 'rejection_reason': reason, 'active': False})

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
