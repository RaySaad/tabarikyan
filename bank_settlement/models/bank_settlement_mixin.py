# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class BankSettlementMixin(models.AbstractModel):
    """
    Mixin مشترك بين كل نماذج السداد البنكي (السلف، الرسوم الحكومية،
    تحويلات المركبات، التأمين الطبي، تصفيات المناديب).

    يوفر:
    - دورة حياة موحّدة (مسودة -> تحت المراجعة -> مؤكدة -> منفّذة)
    - الربط بالموظف/المندوب وبيانات الإقامة
    - الربط بالمنصة (كيتا/هنقرستيشن/جاهز) عبر الحساب التحليلي
      (نفس منطق العزل المالي المستخدم في recruitment_workflow)
    - بيانات السداد البنكي (تاريخ التحويل، رقم السداد، مرفق الإثبات)
    - تتبع كامل عبر mail.thread (Chatter)

    ملاحظة: هذا mixin تجريدي (AbstractModel) — كل نموذج فرعي يحدد
    قيم/تسميات حقل state الخاصة به حسب سياقه (مثال: "تم الصرف" للسلف
    مقابل "تم التحويل" لتحويلات المركبات).
    """
    _name = 'bank.settlement.mixin'
    _description = 'Bank Settlement Mixin'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='الكود', required=True, copy=False, readonly=True,
        default=lambda self: ('New'),
    )

    # -- بيانات الموظف / المندوب --------------------------------------
    # يستخدم recruitment_workflow نموذج hr.employee القياسي مباشرة (لا يوجد
    # نموذج "مندوب" مخصص منفصل) - المنصة الحالية للمندوب متاحة عبر
    # employee_id.project_id، وشريكه الشخصي عبر employee_id._get_personal_partner().
    # ليس required=True على مستوى Python عمداً - يبقى إلزامياً في كل
    # الشاشات (required="1" في كل عروض الفورم) لمن يُنشئ السجل يدوياً، لكن
    # هذا يسمح لكود آلي محدَّد (bank.settlement.government.fee المُنشأ
    # تلقائياً من recruitment.request قبل وجود سجل الموظف الرسمي) بإنشاء
    # السجل بدون موظف مؤقتاً، ثم إكمال الحقل تلقائياً لاحقاً.
    employee_id = fields.Many2one(
        'hr.employee', string='اسم الموظف', tracking=True,
    )
    # رقم الإقامة يُشتق مباشرة من hr.version (عبر _inherits على hr.employee)
    # - نفس الرقم المستخدم في recruitment_workflow (identification_id) -
    # وليس حقلاً مدخلاً يدوياً منفصلاً قد يتعارض مع ملف الموظف الفعلي.
    residency_number = fields.Char(
        string='رقم الإقامة', related='employee_id.identification_id',
        store=True, readonly=True,
    )
    employee_category = fields.Selection(
        selection=[
            ('full_time_rep', 'Full Time مندوب'),
            ('foreign_admin', 'موظف إداري أجنبي'),
        ],
        string='نوع الموظف', tracking=True,
    )

    # -- الربط بالمنصة (كيتا / هنقرستيشن / جاهز) -----------------------
    # المنصة في recruitment_workflow هي project.project (وليست حساباً
    # تحليلياً مباشرة) - كل منصة لها حساب تحليلي خاص بها (project_id.
    # account_id) يُشتق منه تلقائياً هنا، بدل اختيار الحساب التحليلي يدوياً
    # بمعزل عن المنصة الفعلية.
    project_id = fields.Many2one(
        'project.project', string='المنصة', tracking=True,
        help='المنصة (كيتا/هنقرستيشن/جاهز) - تُقترح تلقائياً من المنصة '
             'الحالية للموظف المختار، ويمكن تغييرها يدوياً إن لزم.',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='الحساب التحليلي',
        related='project_id.account_id', store=True, readonly=True,
        help='يُشتق تلقائياً من المنصة المختارة أعلاه - لتحقيق العزل '
             'المالي لكل منصة في القيود المحاسبية.',
    )
    operating_system = fields.Char(string='نظام التشغيل')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.project_id:
            self.project_id = self.employee_id.project_id
        # الشركة تُشتق من فرع الموظف نفسه - بدل تركها على الشركة النشطة
        # افتراضياً في جلسة من ينشئ السجل (غالباً الشركة الرئيسية إن لم
        # يُبدّلها المستخدم يدوياً)، والتي قد تختلف عن فرع الموظف الفعلي.
        if self.employee_id and self.employee_id.company_id:
            self.company_id = self.employee_id.company_id

    # -- المبالغ والعملة -------------------------------------------------
    amount = fields.Monetary(string='المبلغ', tracking=True)
    tax_amount = fields.Monetary(string='مبلغ الضريبة')
    total_amount = fields.Monetary(
        string='الإجمالي', compute='_compute_total_amount', store=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )

    # -- المحاسبة ---------------------------------------------------------
    linked_account_id = fields.Many2one(
        'account.account', string='الحساب المرتبط',
        help='حساب الأستاذ العام المرتبط بهذا النوع من المصروفات',
    )
    journal_id = fields.Many2one(
        'account.journal', string='دفتر اليومية',
        domain="[('company_id', 'parent_of', company_id)]",
        help='الدفتر الذي سيُسجَّل فيه هذا القيد - يُحدَّد صراحة بدل '
             'اختيار أول دفتر بنكي متاح تلقائياً. غير مقيَّد بنوع "بنكي" '
             'فقط، حتى تختار دفاتر مخصصة موجودة أصلاً لديكم (مثل "المدفوعات '
             'الحكومية")، دون الحاجة لفاتورة مورد أو شريك محدَّد - القيد '
             'يُسجَّل مباشرة بلا حاجة لربطه بجهة/شريك معيّن. تشمل القائمة '
             'أيضاً دفاتر الشركة الرئيسية (الأعلى في تسلسل الفروع) - '
             'نفس منطق الفروع المستخدم في كل شاشات المحاسبة القياسية '
             'بـ Odoo، لا تقتصر على دفاتر فرعكم فقط.',
    )
    move_id = fields.Many2one(
        'account.move', string='القيد المحاسبي', readonly=True, copy=False,
    )

    # -- السداد البنكي -----------------------------------------------------
    transfer_date = fields.Date(string='تاريخ التحويل', tracking=True)
    bank_reference = fields.Char(string='رقم السداد البنكي')
    attachment_count = fields.Integer(
        string='عدد المرفقات', compute='_compute_attachment_count',
    )

    notes = fields.Text(string='ملاحظات')

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'منفّذة'),
            ('cancel', 'ملغاة'),
        ],
        string='الحالة', default='draft', tracking=True, copy=False,
    )

    @api.depends('amount', 'tax_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = (rec.amount or 0.0) + (rec.tax_amount or 0.0)

    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = self.env['ir.attachment'].search_count([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id),
            ])

    def _fill_employee_derived_vals(self, vals):
        """يشتق المشروع/الشركة من الموظف المحدَّد في vals['employee_id']
        صراحة، بنفس منطق _onchange_employee_id أعلاه - لكن من جهة
        الخادم مباشرة، بدل الاعتماد فقط على onchange في نموذج الواجهة.
        ضروري لأن onchange وحده لا يكفي: (1) الحقل قد لا يكون معروضاً في
        كل الشاشات فيُهمَل التحديث المرئي عند الحفظ، (2) create()/write()
        القادمة من RPC/API مباشرة لا تمر بـ onchange إطلاقاً."""
        if not vals.get('employee_id'):
            return
        employee = self.env['hr.employee'].browse(vals['employee_id'])
        if 'project_id' not in vals and employee.project_id:
            vals['project_id'] = employee.project_id.id
        if 'company_id' not in vals and employee.company_id:
            vals['company_id'] = employee.company_id.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self._get_sequence_code_for_create(vals)
            self._fill_employee_derived_vals(vals)
        return super().create(vals_list)

    def _get_locked_fields_after_approval(self):
        """الحقول التي تُحدِّد هوية الطرف والمبلغ الفعلي للسداد - لا يجوز
        تعديلها بعد اعتماد المدير العام (تأكيد) فما فوق، بغض النظر عمّن
        أنشأ السجل أو من يحاول التعديل، وبغض النظر عن وجود قيد محاسبي من
        عدمه بعد - وإلا أصبحت الموافقة نفسها بلا معنى (يُعتمَد على مبلغ/
        شخص، ثم يُغيَّران بعد الاعتماد مباشرة). النماذج الفرعية التي لها
        حقول هوية/مبلغ إضافية خاصة بها (نوع الرسوم، الجهة، السيارة...)
        تُضيفها هنا عبر تجاوز هذه الدالة.

        ملاحظة: linked_account_id/journal_id ليسا هنا عمداً - لهما نافذة
        تعديل خاصة تبدأ بعد الاعتماد تحديداً (انظر _get_bank_fields_
        editable_state أدناه)، بما أنهما لا يظهران أصلاً في الواجهة قبل
        ذلك (لا معنى لقفلهما بنفس شرط "مسودة/تحت المراجعة" كباقي الحقول
        هنا)."""
        # project_id (المنصة) مقفول هنا مع employee_id عمداً - يُشتق تلقائياً
        # من منصة الموظف المختار (انظر _fill_employee_derived_vals/
        # _onchange_employee_id أعلاه)، وحساب المنصة التحليلي (analytic_
        # account_id) يُحسَب منه مباشرة - فالسماح بتعديله يدوياً بعد
        # الاعتماد يُتيح تغيير العزل المالي بين المنصات (كيتا/هنقرستيشن/
        # جاهز) لسجل مُعتمَد فعلاً، رغم قفل الموظف نفسه.
        return ['employee_id', 'project_id', 'amount', 'tax_amount']

    def _get_editable_states(self):
        """الحالات التي يُسمح فيها بتعديل الحقول الحساسة أعلاه - قبل
        اعتماد المدير العام. النماذج التي تُسمّي حالاتها بأسماء مختلفة
        (advance.py مثلاً: waiting_approval بدل under_review) تُجاوز هذه
        الدالة."""
        return ('draft', 'under_review')

    _BANK_FIELDS = ('linked_account_id', 'journal_id')

    def _get_bank_fields_editable_state(self):
        """الحالة الوحيدة التي يُسمح فيها بتحديد دفتر اليومية/الحساب
        المرتبط - بعد اعتماد المدير العام تحديداً (وهي أول مرة يظهران
        فيها بالواجهة أصلاً، انظر الشاشات المختلفة) وقبل تسجيل السداد/
        التحويل الفعلي (بعدها تُستخدَم قيمتهما لإنشاء القيد المحاسبي،
        فلا معنى لتغييرهما). النماذج التي تُسمّي حالة الاعتماد باسم
        مختلف (advance.py: 'approved' بدل 'confirmed') تُجاوز هذه
        الدالة."""
        return 'confirmed'

    def write(self, vals):
        skip_lock = self.env.context.get('bank_settlement_skip_approval_lock')
        locked = self._get_locked_fields_after_approval()
        # يُتجاوز القفل عمداً لعملية نظامية واحدة: إكمال حقل الموظف
        # تلقائياً بمجرد إنشاء سجله الرسمي (hr.employee) في recruitment_
        # workflow - يستهدف نفس الشخص المرشّح بالضبط (لا تغيير فعلي "لمن")،
        # وليس تعديلاً يدوياً حقيقياً. انظر bank_settlement/models/
        # recruitment_request.py: _create_employee().
        if any(f in vals for f in locked) and not skip_lock:
            for rec in self:
                if rec.state not in rec._get_editable_states():
                    raise UserError(
                        'لا يمكن تعديل بيانات السداد الأساسية (الموظف/'
                        'المنصة/المبلغ) بعد اعتماد المدير العام - '
                        'أعد السجل لمسودة أولاً (زر "إعادة لمسودة") إن '
                        'احتجت تصحيحها.'
                    )
        if any(f in vals for f in self._BANK_FIELDS) and not skip_lock:
            for rec in self:
                if rec.state != rec._get_bank_fields_editable_state():
                    raise UserError(
                        'دفتر اليومية والحساب المرتبط لا يمكن تحديدهما إلا '
                        'بعد اعتماد المدير العام مباشرة، وقبل تسجيل السداد/'
                        'التحويل الفعلي.'
                    )
        self._fill_employee_derived_vals(vals)
        return super().write(vals)

    def _get_sequence_code_for_create(self, vals):
        """كل نموذج فرعي يجب أن يحدد كود التسلسل الخاص به."""
        seq_code = self._sequence_code()
        return self.env['ir.sequence'].next_by_code(seq_code) or 'New'

    def _sequence_code(self):
        raise NotImplementedError(
            'يجب تعريف _sequence_code() في كل نموذج فرعي'
        )

    # -- انتقالات الحالة ----------------------------------------------------
    def _check_group(self, *group_xmlids):
        """طبقة حماية من جهة الخادم للانتقالات الحساسة - لا تعتمد فقط على
        إخفاء الأزرار في الواجهة (والتي يمكن تجاوزها عبر RPC/API مباشرة)."""
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError('ليست لديك الصلاحية للقيام بهذا الإجراء.')

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('يمكن إرسال السجلات في حالة "مسودة" فقط للمراجعة.')
        self.write({'state': 'under_review'})

    def action_confirm(self):
        """التأكيد (تحت المراجعة -> مؤكدة) - يقتصر على المدير العام، حسب
        سير العمل الفعلي المطلوب."""
        for rec in self:
            if rec.state != 'under_review':
                raise UserError('يمكن تأكيد السجلات في حالة "تحت المراجعة" فقط.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'confirmed'})

    def action_done(self):
        """إتمام السداد/التحويل — ينشئ القيد المحاسبي إن لم يكن موجوداً.
        متاح للمراجع/المحاسب فما فوق (بعد اعتماد المدير العام مسبقاً)."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError('يجب تأكيد السجل أولاً قبل إتمامه.')
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
            if not rec.move_id:
                rec.move_id = rec._create_settlement_move()
        self.write({'state': 'done'})

    def action_reset_draft(self):
        """إعادة لمسودة - تُلغي فعلياً أي اعتماد سابق (المدير العام)،
        فتتطلب نفس صلاحيته تحديداً - وليست متاحة لمن ينشئ السجل فقط."""
        for rec in self:
            # القيد المحاسبي (إن وُجد) يعني أن السداد وثّق فعلياً محاسبياً -
            # لا يجوز إعادة السجل لمسودة وترك ذلك القيد معلّقاً بلا مرجع.
            # يجب عكس/إلغاء القيد أولاً من شاشة المحاسبة نفسها.
            if rec.move_id:
                raise UserError(
                    'لا يمكن إعادة هذا السجل لمسودة - يوجد قيد محاسبي مرتبط '
                    'به بالفعل (%s). ألغِ/اعكس القيد أولاً من المحاسبة.'
                    % rec.move_id.name
                )
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'draft'})

    def action_cancel(self):
        """إلغاء - متاح للمراجع فما فوق (وليس لمن ينشئ السجل فقط)."""
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(
                    'لا يمكن إلغاء هذا السجل - القيد المحاسبي المرتبط به '
                    'مرحّل بالفعل (%s). ألغِه/اعكسه من المحاسبة أولاً.'
                    % rec.move_id.name
                )
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
        self.write({'state': 'cancel'})

    def _get_settlement_partner_id(self):
        """الشريك المستخدَم على سطر القيد المحاسبي - افتراضياً شريك
        الموظف الشخصي إن كان محدَّداً. النماذج الفرعية قد تتجاوزها إن
        احتاجت شريكاً آخر (مثال: bank.settlement.government.fee يفضّل
        حقل partner_id صريحاً قد يُضبط قبل وجود سجل الموظف الرسمي)."""
        self.ensure_one()
        return self.employee_id._get_personal_partner().id if self.employee_id else False

    def _create_settlement_move(self):
        """ينشئ قيد محاسبي (account.move) لتوثيق عملية السداد، بدفتر
        اليومية البنكي المحدَّد صراحة وحسابه المقابل الرسمي، مع توزيع
        تحليلي على حساب المنصة المشتق من الموظف/المشروع."""
        self.ensure_one()
        if not self.linked_account_id:
            raise UserError(
                'لا يمكن إنشاء القيد المحاسبي بدون تحديد "الحساب المرتبط".'
            )
        if not self.journal_id:
            raise UserError(
                'لا يمكن إنشاء القيد المحاسبي بدون تحديد "دفتر اليومية البنكي".'
            )

        move_vals = {
            'journal_id': self.journal_id.id,
            # نضبط الشركة صراحة من شركة السجل نفسها (المُشتقة من المشروع/
            # الحساب التحليلي) بدل تركها تُحسب تلقائياً من الشركة النشطة
            # في جلسة من يضغط الزر - حتى يُسجَّل القيد دائماً على الفرع
            # الصحيح بشكل حتمي، حتى لو استخدم دفتر يومية الشركة الرئيسية
            # المشتركة (انظر domain حقل journal_id أعلاه).
            'company_id': self.company_id.id,
            # يُستخدم لحصر رؤية "مستخدم/مراجع" السداد البنكي على قيودهم
            # فقط عبر ir.rule - دون كشف بقية قيود المحاسبة في الشركة.
            'is_bank_settlement_move': True,
            'date': self.transfer_date or fields.Date.context_today(self),
            'ref': self.name,
            'line_ids': [
                (0, 0, {
                    'name': self.name,
                    'account_id': self.linked_account_id.id,
                    'partner_id': self._get_settlement_partner_id(),
                    'debit': self.total_amount,
                    'credit': 0.0,
                    'analytic_distribution': (
                        {str(self.analytic_account_id.id): 100}
                        if self.analytic_account_id else False
                    ),
                }),
                (0, 0, {
                    'name': self.name,
                    'account_id': self.journal_id.default_account_id.id,
                    'debit': 0.0,
                    'credit': self.total_amount,
                }),
            ],
        }
        # sudo(): إنشاء القيد نفسه لا يجب أن يشترط عضوية "مستخدم/مراجع
        # السداد البنكي" في إحدى مجموعات المحاسبة الأصلية بـ Odoo (فوترة،
        # محاسب...) - الصلاحية الفعلية لهذا الإجراء محكومة بالفعل عبر
        # _check_group في action_done قبل الوصول هنا. اشتراط عضوية
        # محاسبية حقيقية كان يفتح لهم أيضاً رؤية بقية تطبيق المحاسبة
        # (عملاء/موردين/فواتير) رغم أنهم لا يحتاجونها.
        move = self.env['account.move'].sudo().create(move_vals)
        return move.id

    def action_view_move(self):
        """يفتح القيد/الفاتورة المحاسبية الرئيسية المرتبطة بهذا السداد -
        بدون هذا الزر، القيد يُنشأ فعلياً عند الإتمام لكن لا توجد وسيلة
        مباشرة للوصول إليه من شاشة السداد نفسها."""
        self.ensure_one()
        if not self.move_id:
            raise UserError('لا يوجد قيد محاسبي مرتبط بعد.')
        return {
            'name': 'القيد المحاسبي',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def action_view_attachments(self):
        self.ensure_one()
        return {
            'name': 'المرفقات',
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }
