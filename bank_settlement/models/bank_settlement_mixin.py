# -*- coding: utf-8 -*-
import calendar
from datetime import timedelta

from odoo import api, fields, models, _
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
    # ondelete='restrict': بدونها (والحقل غير required عمداً) الافتراضي
    # 'set null' - حذف سجل الموظف (hr.employee) كان يُفرغ هذا الحقل بصمت
    # على أي عملية سداد بنكي نشطة (حتى "بانتظار الموافقة") بدل منع الحذف
    # - يترك السجل عالقاً بحقل إلزامي في الواجهة فارغ ولا يمكن حفظه، ويفقد
    # الرابط الرسمي لهوية الموظف نهائياً - ثغرة حقيقية سبّبت فقدان بيانات
    # فعلي (اكتُشفت من بلاغ مستخدم حقيقي).
    employee_id = fields.Many2one(
        'hr.employee', string='اسم الموظف', tracking=True, ondelete='restrict',
    )
    # رقم الإقامة يُشتق مباشرة من hr.version (عبر _inherits على hr.employee)
    # - نفس الرقم المستخدم في recruitment_workflow (identification_id) -
    # وليس حقلاً مدخلاً يدوياً منفصلاً قد يتعارض مع ملف الموظف الفعلي.
    # groups='' صراحة: بدونها يرث هذا الحقل تلقائياً قيد hr.group_hr_user
    # الموجود على identification_id في نواة hr (حماية خصوصية معيارية) - ما
    # يمنع أي مستخدم سداد بنكي (محاسب/مدير عام/مسؤول مشروع) لا يملك تلك
    # الصلاحية من مجرد فتح شاشة السداد البنكي أصلاً (AccessError عند عرض
    # النموذج بالكامل) - ثغرة حقيقية خطيرة اكتُشفت بمحاكاة مستخدم غير
    # إداري (اختبارات الوحدة لم تكتشفها لأن base.user_admin يملك تلك
    # الصلاحية أصلاً فمرّت كل الاختبارات رغم الثغرة).
    residency_number = fields.Char(
        string='رقم الإقامة', related='employee_id.identification_id',
        store=True, readonly=True, groups='',
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
        # sudo() ضروري هنا: project_id/company_id حقلان "خاصان" (Private)
        # من منظور hr.employee (project_id تحديداً حقل مخصَّص أضافه
        # recruitment_workflow، غير مُدرَج في hr.employee.public) - أي
        # مستخدم سداد بنكي عادي (بلا عضوية في مجموعة الموارد البشرية
        # الأصلية hr.group_hr_user) كان سيتلقى AccessError فوراً بمجرد
        # اختيار موظف في أي من الشاشات الخمس، رغم أن هذا القراءة هنا
        # داخلية بحتة (اشتقاق حقل آخر) ولا تعرض بيانات الموظف الخاصة
        # للمستخدم مباشرة - ثغرة حقيقية مكتشفة بالاختبار الفعلي.
        employee = self.employee_id.sudo()
        if employee and employee.project_id:
            self.project_id = employee.project_id
        # الشركة تُشتق من فرع الموظف نفسه - بدل تركها على الشركة النشطة
        # افتراضياً في جلسة من ينشئ السجل (غالباً الشركة الرئيسية إن لم
        # يُبدّلها المستخدم يدوياً)، والتي قد تختلف عن فرع الموظف الفعلي.
        if employee and employee.company_id:
            self.company_id = employee.company_id

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
        'account.account', string='الحساب المرتبط', tracking=True,
        help='حساب الأستاذ العام المرتبط بهذا النوع من المصروفات',
    )
    journal_id = fields.Many2one(
        'account.journal', string='دفتر اليومية', tracking=True,
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
    # -- الدفعة المقدمة (استهلاك دوري مع تتبع تحليلي حسب منصة المندوب) ---
    # طلب صريح: مصاريف تُدفع مقدماً لكن تخص المندوب على مدى فترة زمنية
    # بالأيام (كرت العمل: 90/180/270 يوماً، الفندق: بالأشهر...) - يجب أن
    # يتوزع مصروفها تحليلياً حسب المنصة الفعلية للمندوب في كل فترة، لا
    # منصته وقت السداد فقط (قد يتحوّل بين المنصات أثناء الفترة). بدل قيد
    # فوري واحد (_create_settlement_move)، يُنشأ جدول استحقاق دوري
    # (bank.settlement.prepaid.line - نموذج مملوك بالكامل لهذا الموديول،
    # بلا أي اعتماد على تطبيق "أصول" خارجي) - انظر _create_prepaid_schedule
    # وbank_settlement/models/prepaid_schedule.py لتفاصيل الآلية الكاملة.
    is_prepaid = fields.Boolean(
        string='دفعة مقدمة', tracking=True,
        help='فعّلها إن كان هذا المبلغ يغطي فترة زمنية للمندوب (كرت عمل، '
             'إقامة فندقية...) بدل مصروف فوري - يُوزَّع تحليلياً تلقائياً '
             'حسب منصة المندوب الفعلية خلال الفترة، ويُسوَّى تلقائياً عند '
             'أي نقل منصة أثناء سريانها.',
    )
    prepaid_days = fields.Integer(
        string='عدد أيام التغطية', tracking=True,
        help='الفترة التي يغطيها هذا المبلغ بالأيام بالضبط (مثال: 90، '
             '180، 270) - وليس بالأشهر، حتى لو غير مطابقة لحدود الأشهر '
             'التقويمية.',
    )
    prepaid_category_id = fields.Many2one(
        'bank.settlement.prepaid.category', string='فئة الدفعة المقدمة',
        tracking=True,
        help='تحدد حساب "المصروفات المدفوعة مقدماً" (مثال: 114001) وحساب '
             'المصروف الفعلي ودفتر اليومية المستخدَمة لجدولة الاستحقاق. '
             'تُعَدّ مرة واحدة من إعدادات السداد البنكي.',
    )
    prepaid_line_count = fields.Integer(
        string='عدد أسطر جدول الاستحقاق', compute='_compute_prepaid_line_count',
    )

    move_id = fields.Many2one(
        'account.move', string='القيد المحاسبي', readonly=True, copy=False,
    )

    # -- السداد البنكي -----------------------------------------------------
    transfer_date = fields.Date(string='تاريخ التحويل', tracking=True)
    bank_reference = fields.Char(string='رقم السداد البنكي', tracking=True)
    attachment_count = fields.Integer(
        string='عدد المرفقات', compute='_compute_attachment_count',
    )

    notes = fields.Text(string='ملاحظات')

    # يُفعَّل (False) تلقائياً عند الرفض (انظر action_reject أدناه) - يُخرج
    # السجل المرفوض من القوائم النشطة الافتراضية دون حذفه (سجل التدقيق
    # يبقى كاملاً)، ويبقى متاحاً عبر فلتر "مؤرشف" المعياري في Odoo.
    active = fields.Boolean(default=True)

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'منفّذة'),
            ('rejected', 'مرفوضة'),
            ('cancel', 'ملغاة'),
        ],
        string='الحالة', default='draft', tracking=True, copy=False,
    )
    rejection_reason = fields.Text(string='سبب الرفض', copy=False)
    # ثغرة حقيقية اكتُشفت من الاستخدام الفعلي: "إرجاع للتصحيح" يعيد
    # الحالة نفسها (مثال: under_review) التي تحملها أيضاً السجلات التي
    # لم تُراجَع بعد للمرة الأولى - و_get_editable_states() تقفل الحقول
    # الحساسة (الموظف/المبلغ...) في أي حالة غير "مسودة" (طلب صريح سابق:
    # "القفل يبدأ فور إرسال للمراجعة"). فكان "إرجاع للتصحيح" يُرجع الحالة
    # فعلياً لكن يبقي الحقول مقفولة - يُفرغ الميزة من هدفها الوحيد
    # (التصحيح الفعلي). هذا الحقل يميّز "أُرجعت للتصحيح تحديداً" عن
    # "لم تُراجَع بعد للمرة الأولى" رغم تطابق state في الحالتين - يُضبَط
    # True في action_return_to_previous_stage() أدناه، ويُعاد False
    # تلقائياً فور إعادة المرحلة التالية فعلياً (action_confirm() هنا،
    # أو action_pm_approve()/action_confirm() في advance.py) - أي أن
    # نافذة التصحيح تُغلَق تلقائياً بمجرد إعادة الاعتماد، بما يحافظ على
    # القاعدة الأصلية (القفل فور المراجعة) لكل الحالات الأخرى.
    returned_for_correction = fields.Boolean(
        string='أُرجعت للتصحيح', default=False, copy=False,
        help='تُضبَط تلقائياً عند "إرجاع للتصحيح" - تسمح مؤقتاً بتعديل '
             'الحقول الحساسة (الموظف/المبلغ...) حتى إعادة الاعتماد.',
    )

    @api.depends('amount', 'tax_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = (rec.amount or 0.0) + (rec.tax_amount or 0.0)

    @api.constrains('amount', 'tax_amount')
    def _check_amount_not_negative(self):
        """يمنع أي مبلغ سالب في أي حالة - لا يوجد سيناريو مشروع لمبلغ/
        ضريبة سالبين هنا (كانت ثغرة حقيقية: لا يوجد أي تحقق سابقاً، يمكن
        تمرير مبلغ سالب حتى مرحلة "منفّذة" وإنشاء قيد محاسبي فعلي به)."""
        for rec in self:
            if rec.amount and rec.amount < 0:
                raise UserError('المبلغ لا يمكن أن يكون سالباً.')
            if rec.tax_amount and rec.tax_amount < 0:
                raise UserError('مبلغ الضريبة لا يمكن أن يكون سالباً.')

    def _check_amount_positive_before_submit(self):
        """يتحقق من أن المبلغ موجب فعلياً (وليس صفراً أو فارغاً) قبل
        إرسال السجل للمراجعة - النماذج التي تُسمّي إجراء الإرسال بأسلوب
        مختلف (advance.py: state مختلف) تستدعيها صراحة قبل تنفيذ
        الانتقال."""
        for rec in self:
            if not rec.amount or rec.amount <= 0:
                raise UserError('يجب تحديد مبلغ أكبر من صفر قبل إرسال السجل للمراجعة.')

    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = self.env['ir.attachment'].search_count([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id),
            ])

    def _compute_prepaid_line_count(self):
        for rec in self:
            rec.prepaid_line_count = self.env['bank.settlement.prepaid.line'].search_count([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id),
            ])

    def action_view_prepaid_lines(self):
        """يفتح جدول استحقاق "الدفعة المقدمة" الخاص بهذا السجل - انظر
        prepaid_schedule.py."""
        self.ensure_one()
        return {
            'name': 'جدول استحقاق الدفعة المقدمة',
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.prepaid.line',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }

    def _fill_employee_derived_vals(self, vals):
        """يشتق المشروع/الشركة من الموظف المحدَّد في vals['employee_id']
        صراحة، بنفس منطق _onchange_employee_id أعلاه - لكن من جهة
        الخادم مباشرة، بدل الاعتماد فقط على onchange في نموذج الواجهة.
        ضروري لأن onchange وحده لا يكفي: (1) الحقل قد لا يكون معروضاً في
        كل الشاشات فيُهمَل التحديث المرئي عند الحفظ، (2) create()/write()
        القادمة من RPC/API مباشرة لا تمر بـ onchange إطلاقاً."""
        if not vals.get('employee_id'):
            return
        # sudo() لنفس سبب _onchange_employee_id أعلاه - create()/write()
        # يُنفَّذان باسم المستخدم الفعلي (وليس onchange وحده)، فبلا sudo()
        # هنا كان أي "مستخدم" سداد بنكي عادي (بلا hr.group_hr_user) سيفشل
        # بمجرد محاولة إنشاء سجل بموظف محدَّد.
        employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
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

        ملاحظة: linked_account_id/journal_id/transfer_date/bank_reference
        ليست هنا عمداً - لها نافذة تعديل خاصة تبدأ بعد الاعتماد تحديداً
        (انظر _get_bank_fields_editable_state أدناه)، بما أنها بيانات
        السداد الفعلي (خاصة بالمحاسب وقت الصرف تحديداً) ولا تظهر أصلاً
        في الواجهة قبل ذلك - لا معنى لقفلها بنفس شرط "مسودة/تحت
        المراجعة" كباقي الحقول هنا."""
        # project_id (المنصة) مقفول هنا مع employee_id عمداً - يُشتق تلقائياً
        # من منصة الموظف المختار (انظر _fill_employee_derived_vals/
        # _onchange_employee_id أعلاه)، وحساب المنصة التحليلي (analytic_
        # account_id) يُحسَب منه مباشرة - فالسماح بتعديله يدوياً بعد
        # الاعتماد يُتيح تغيير العزل المالي بين المنصات (كيتا/هنقرستيشن/
        # جاهز) لسجل مُعتمَد فعلاً، رغم قفل الموظف نفسه.
        # company_id: ثغرة حقيقية اكتُشفت بمراجعة شاملة (تدقيق صلاحيات
        # Studio) - كان الحقل يظهر readonly="1" في كل الشاشات (تسهيل
        # واجهة فقط)، بلا أي حماية فعلية من جهة الخادم؛ تعديله مباشرة
        # (عبر RPC، أو بعد إزالة قيد الواجهة عبر Studio) كان يغيّر الفرع/
        # الشركة المحاسبية لسجل مُعتمَد فعلاً بلا أي مانع. يُشتق تلقائياً
        # من فرع الموظف فقط (انظر _fill_employee_derived_vals)، ولا يُشترط
        # تعديله يدوياً منفصلاً عنه أصلاً.
        return [
            'employee_id', 'employee_category', 'project_id', 'amount',
            'tax_amount', 'company_id',
        ]

    def _get_editable_states(self):
        """الحالات التي يُسمح فيها بتعديل الحقول الحساسة أعلاه - "مسودة"
        فقط، أي أن القفل يبدأ فور "إرسال للمراجعة" مباشرة، قبل أي اعتماد
        فعلي - بناءً على طلب صريح (بنفس قاعدة السلفة والتي كانت أشد من
        بقية الشاشات، عُمِّمت الآن على الجميع)."""
        return ('draft',)

    def _get_correction_editable_fields(self):
        """من بين حقول _get_locked_fields_after_approval() أعلاه، هذه
        فقط التي يُسمح بتعديلها أثناء نافذة "إرجاع للتصحيح" المؤقتة
        (returned_for_correction=True) - طلب صريح: "فقط يتعدل المبلغ...
        اما الاسم فلا يفتح" - أي أن هوية الموظف/المنصة تبقى مقفولة
        دائماً (لا تُصحَّح بهذه الطريقة؛ لو كان الموظف خاطئاً من الأساس
        فالحل رفض السجل وإنشاء سجل صحيح جديد)، ويُقتصر التصحيح المؤقت
        على المبلغ فقط. النموذج الفرعي الذي يستخدم اسماً بديلاً للمبلغ
        (representative_settlement.py: settlement_amount) يُضيفه هنا."""
        return ['amount']

    # دفتر اليومية/الحساب المرتبط/تاريخ التحويل/رقم السداد البنكي - كلها
    # بيانات السداد الفعلي التي يُدخلها المحاسب تحديداً وقت صرف المبلغ
    # فعلياً، لا قبل ذلك (طلب صريح: "تاريخ التحويل... خاص بالمحاسبة عند
    # صرف المبلغ - خليه مفعل لآخر خطوة وبعدها اغلقه بعد تم الصرف").
    _BANK_FIELDS = ('linked_account_id', 'journal_id', 'transfer_date', 'bank_reference')

    def _get_locked_bank_fields(self):
        """الحقول ضمن _BANK_FIELDS التي لا تزال مقفولة فعلياً حتى مرحلة
        الاعتماد - النموذج الفرعي يمكنه استثناء حقل منها بتجاوز هذه
        الدالة (مثال: government_fee.py يستثني bank_reference، لأنه
        متعلق أصلاً بمن يرفع الطلب نفسه - طلب صريح: "خلي رقم السداد
        مفتوح من البداية" - وليس بالمحاسب وقت الصرف كباقي حقول السداد)."""
        return self._BANK_FIELDS

    def _get_bank_fields_editable_state(self):
        """الحالة الوحيدة التي يُسمح فيها بتحديد بيانات السداد الفعلي
        (دفتر اليومية، الحساب المرتبط، تاريخ التحويل، رقم السداد البنكي)
        - بعد اعتماد المدير العام تحديداً (وهي أول مرة تظهر فيها بالواجهة
        أصلاً، انظر الشاشات المختلفة) وقبل تسجيل السداد/التحويل الفعلي
        (بعدها تُستخدَم قيمها لإنشاء القيد المحاسبي، فلا معنى لتغييرها).
        النماذج التي تُسمّي حالة الاعتماد باسم مختلف (advance.py:
        'approved' بدل 'confirmed') تُجاوز هذه الدالة."""
        return 'confirmed'

    def write(self, vals):
        skip_lock = self.env.context.get('bank_settlement_skip_approval_lock')
        locked = self._get_locked_fields_after_approval()
        # يُتجاوز القفل عمداً لعملية نظامية واحدة: إكمال حقل الموظف
        # تلقائياً بمجرد إنشاء سجله الرسمي (hr.employee) في recruitment_
        # workflow - يستهدف نفس الشخص المرشّح بالضبط (لا تغيير فعلي "لمن")،
        # وليس تعديلاً يدوياً حقيقياً. انظر bank_settlement/models/
        # recruitment_request.py: _create_employee().
        locked_in_vals = [f for f in vals if f in locked]
        if locked_in_vals and not skip_lock:
            for rec in self:
                if rec.state in rec._get_editable_states():
                    continue
                # أثناء نافذة "إرجاع للتصحيح" المؤقتة، يُسمح فقط بتعديل
                # الحقول ضمن _get_correction_editable_fields() (المبلغ
                # تحديداً) - هوية الموظف/المنصة تبقى مقفولة دائماً حتى
                # لو أُرجع السجل للتصحيح (طلب صريح).
                correction_fields = (
                    rec._get_correction_editable_fields() if rec.returned_for_correction else ()
                )
                disallowed = [f for f in locked_in_vals if f not in correction_fields]
                if disallowed:
                    raise UserError(
                        'لا يمكن تعديل بيانات السداد الأساسية (الموظف/'
                        'المنصة) بعد اعتماد المدير العام. استخدم "إرجاع '
                        'للتصحيح" لتعديل المبلغ فقط، أو ارفض السجل وأنشئ '
                        'سجلاً جديداً صحيحاً إن كان الموظف نفسه خاطئاً.'
                    )
        if any(f in vals for f in self._get_locked_bank_fields()) and not skip_lock:
            for rec in self:
                # نافذة "إرجاع للتصحيح" تفتح بيانات السداد البنكي مؤقتاً
                # أيضاً (رقم السداد/الحساب المرتبط/دفتر اليومية) - طلب
                # صريح - وليس فقط حالة "مؤكدة" القياسية.
                if rec.state != rec._get_bank_fields_editable_state() and not rec.returned_for_correction:
                    raise UserError(
                        'بيانات السداد الفعلي (دفتر اليومية، الحساب المرتبط، '
                        'تاريخ التحويل، رقم السداد البنكي) لا يمكن تحديدها '
                        'إلا بعد اعتماد المدير العام مباشرة، وقبل تسجيل '
                        'السداد/التحويل الفعلي (أو أثناء "إرجاع للتصحيح").'
                    )
        self._fill_employee_derived_vals(vals)
        res = super().write(vals)
        if 'state' in vals:
            for rec in self:
                rec._schedule_stage_activity()
        return res

    def _get_first_group_user(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return group.all_user_ids[:1] if group else self.env['res.users']

    def _get_stage_responsible_user(self):
        """المستخدم الذي يجب تنبيهه بضرورة اتخاذ إجراء في الحالة الحالية -
        كان السداد البنكي بلا أي إشعار فعلي إطلاقاً سابقاً (يجب تفقّد
        القوائم يدوياً). النماذج التي تُسمّي حالاتها بأسماء مختلفة
        (advance.py) تُجاوز هذه الدالة."""
        self.ensure_one()
        if self.state == 'under_review':
            return self._get_first_group_user('bank_settlement.group_bank_settlement_manager')
        if self.state == 'confirmed':
            return self._get_first_group_user('bank_settlement.group_bank_settlement_reviewer')
        if self.state == 'rejected':
            return self.create_uid
        return self.env['res.users']

    def _schedule_stage_activity(self):
        """يُنهي أي نشاط سابق متعلق بهذا السجل (الحالة تغيّرت، فالإجراء
        المطلوب سابقاً لم يعد ذا قيمة) ثم يجدول تنبيهاً جديداً لصاحب
        القرار في الحالة الجديدة (إن وُجد)، بقناتين معاً:
        1. نشاط (Activity/To-Do) - يبقى ظاهراً حتى يُنجَز، في شاشة
           "الأنشطة" المنفصلة (لا يظهر في صندوق الدردشة/الجرس).
        2. رسالة مباشرة في صندوق الدردشة (Discuss/الجرس) - أسرع للملاحظة
           لكن يمكن تجاهلها أو ضياعها بسهولة، طلب صريح بالإضافة للنشاط
           وليس بديلاً عنه."""
        self.ensure_one()
        self.activity_ids.action_feedback(feedback='تغيّرت حالة السجل')
        user = self._get_stage_responsible_user()
        if not user:
            return
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary='مطلوب إجراؤك: %s' % self.name,
            user_id=user.id,
        )
        if user.partner_id:
            self.message_post(
                body='مطلوب إجراؤك على %s.' % self.name,
                partner_ids=user.partner_id.ids,
            )

    def unlink(self):
        # سجلات السداد البنكي سجل تدقيق ومراجعة دائم - يُمنع حذفها نهائياً
        # بعد مغادرة "مسودة" (حتى لممن يملك صلاحية الحذف على مستوى ir.
        # model.access، مثل مدير عام السداد البنكي)، حفاظاً على أثر كامل
        # لكل سجل رُفع للمراجعة أو اعتُمد أو نُفِّذ فعلياً - بنفس مبدأ
        # recruitment_workflow.recruitment_request.unlink(). "إرجاع للتصحيح"
        # هو البديل الوحيد لمن غادر "مسودة" ضمن سير العمل الطبيعي. يُتجاوز
        # الشرط عمداً عبر نفس سياق تجاوز القفل العام
        # (bank_settlement_skip_approval_lock) في حالة نظامية واحدة محدَّدة
        # فقط، وليس حذفاً يدوياً حراً: حذف سجل "الرسوم الحكومية" غير
        # المسدَّد بعد عند "إرجاع للتصحيح" من recruitment_workflow (انظر
        # bank_settlement/models/recruitment_request.py:
        # _unlock_gov_fee_for_correction).
        if not self.env.context.get('bank_settlement_skip_approval_lock'):
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(
                        'لا يمكن حذف هذا السجل نهائياً بعد مغادرة "مسودة" - '
                        'للحفاظ على سجل تدقيق ومراجعة كامل. استخدم "رفض" '
                        'أو "إرجاع للتصحيح" بدلاً من ذلك إن احتجت إيقافه.'
                    )
        return super().unlink()

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
        self._check_amount_positive_before_submit()
        self.write({'state': 'under_review'})

    def action_confirm(self):
        """التأكيد (تحت المراجعة -> مؤكدة) - يقتصر على المدير العام، حسب
        سير العمل الفعلي المطلوب."""
        for rec in self:
            if rec.state != 'under_review':
                raise UserError('يمكن تأكيد السجلات في حالة "تحت المراجعة" فقط.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        # إعادة الاعتماد فعلياً تُغلق نافذة التصحيح المؤقتة (returned_for_
        # correction) - انظر شرحها عند تعريف الحقل أعلاه.
        self.write({'state': 'confirmed', 'returned_for_correction': False})

    def action_done(self):
        """إتمام السداد/التحويل — ينشئ القيد المحاسبي إن لم يكن موجوداً
        (أو القيد الأولي + جدول استحقاق "دفعة مقدمة" كامل إن كان
        is_prepaid مفعَّلاً - انظر _create_prepaid_schedule). متاح
        للمحاسب فما فوق (بعد اعتماد المدير العام مسبقاً)."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError('يجب تأكيد السجل أولاً قبل إتمامه.')
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
            if rec.is_prepaid:
                if not rec.move_id:
                    rec.move_id = rec._create_prepaid_schedule()
            elif not rec.move_id:
                rec.move_id = rec._create_settlement_move()
        self.write({'state': 'done'})

    def _compute_prepaid_schedule_lines(self, start_date, end_date, total_amount):
        """يبني جدول استهلاك دقيق بالأيام (وليس بتقريب شهري) - لكل شهر
        تقويمي يتقاطع مع [start_date, end_date]، يُحسَب مبلغه بنسبة عدد
        أيام التداخل الفعلي مع إجمالي أيام الفترة كاملة، مهما كان عدد
        الأيام (90، 180، 270، أو أي رقم آخر) ومهما كان يوم البداية.
        السطر الأخير يمتص فرق التقريب (Rounding) ليبقى المجموع مطابقاً
        تماماً للمبلغ الإجمالي دائماً. يُعيد قائمة
        (period_start, period_end, amount)."""
        total_days = (end_date - start_date).days + 1
        if total_days <= 0:
            raise UserError(_('فترة تغطية الدفعة المقدمة غير صحيحة.'))
        currency_decimals = self.currency_id.decimal_places
        lines = []
        cur = start_date
        remaining_amount = total_amount
        while cur <= end_date:
            month_last_day = calendar.monthrange(cur.year, cur.month)[1]
            month_end = cur.replace(day=month_last_day)
            period_end = min(month_end, end_date)
            days_in_period = (period_end - cur).days + 1
            if period_end >= end_date:
                amount = remaining_amount  # السطر الأخير: يمتص فرق التقريب
            else:
                amount = round(total_amount * days_in_period / total_days, currency_decimals)
            remaining_amount -= amount
            lines.append((cur, period_end, amount))
            cur = period_end + timedelta(days=1)
        return lines

    def _create_prepaid_schedule(self):
        """يسجّل السداد الفعلي فوراً (مديناً حساب "المصروفات المدفوعة
        مقدماً"، دائناً دفتر اليومية البنكي المحدَّد كالمعتاد) بكامل
        المبلغ، ثم يبني جدول استحقاق دوري دقيق بالأيام
        (bank.settlement.prepaid.line - انظر _compute_prepaid_schedule_
        lines للحساب، وprepaid_schedule.py._post_entry للتوزيع التحليلي
        الديناميكي حسب منصة المندوب عند ترحيل كل سطر). يعيد قيد السداد
        الأولي (id) ليُخزَّن في move_id، بنفس دور _create_settlement_move
        للسجلات غير المدفوعة مقدماً."""
        self.ensure_one()
        if not self.prepaid_category_id:
            raise UserError(_('يجب تحديد "فئة الدفعة المقدمة" أولاً.'))
        if self.prepaid_days <= 0:
            raise UserError(_('يجب تحديد "عدد أيام التغطية" أولاً (أكبر من صفر).'))
        if not self.employee_id:
            raise UserError(_('يجب تحديد الموظف/المندوب أولاً.'))
        if not self.journal_id:
            raise UserError(
                'لا يمكن إنشاء القيد المحاسبي بدون تحديد "دفتر اليومية البنكي".'
            )
        start_date = self.transfer_date or fields.Date.context_today(self)
        end_date = start_date + timedelta(days=self.prepaid_days - 1)
        schedule = self._compute_prepaid_schedule_lines(start_date, end_date, self.total_amount)
        category = self.prepaid_category_id

        # القيد الأولي: يسجّل الخروج الفعلي للنقد الآن بكامله (مديناً
        # حساب المصروفات المدفوعة مقدماً، دائناً دفتر اليومية البنكي) -
        # نفس بنية _create_settlement_move العادية، لكن الطرف المدين هنا
        # هو حساب "المصروفات المدفوعة مقدماً" بدل حساب المصروف الفعلي
        # مباشرة (يُستنفَد تدريجياً بكل قيد استحقاق دوري لاحق).
        # analytic_distribution: False صراحة على كلا السطرين - هذا قيد
        # نقدي بحت بين حسابين في الميزانية (لا مصروف بعد)، فلا معنى
        # لتوزيعه تحليلياً بحسب منصة. صراحة (بدل تركه بلا قيمة) لمنع
        # نموذج account.analytic.distribution.model العام (يُحدِّثه
        # recruitment_workflow.hr_employee._sync_partner_analytic_
        # distribution لكل شريك عند أي نقل منصة، لأغراض أخرى) من ملء هذا
        # القيد تلقائياً بتوزيع غير مقصود - انظر نفس الثغرة المشروحة في
        # prepaid_schedule.py._post_entry.
        move_vals = {
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'is_bank_settlement_move': True,
            'date': start_date,
            'ref': self.name,
            'line_ids': [
                (0, 0, {
                    'name': self.name,
                    'account_id': category.prepaid_account_id.id,
                    'partner_id': self._get_settlement_partner_id(),
                    'debit': self.total_amount,
                    'credit': 0.0,
                    'analytic_distribution': False,
                }),
                (0, 0, {
                    'name': self.name,
                    'account_id': self.journal_id.default_account_id.id,
                    'debit': 0.0,
                    'credit': self.total_amount,
                    'analytic_distribution': False,
                }),
            ],
        }
        # يُرحَّل فوراً (بخلاف _create_settlement_move العادية التي تُبقي
        # قيدها مسودة لمراجعة محاسب لاحقة) - المبلغ هنا خرج فعلياً وبالكامل
        # فور "تم" (نفس مبدأ "بلا مراجعة بشرية" الذي طُلب صراحة لكامل آلية
        # الدفعة المقدمة، ولضمان ظهوره فوراً في رصيد حساب "المصروفات
        # المدفوعة مقدماً" - كان يبقى مسودة سابقاً فلا ينعكس في الرصيد
        # الفعلي إلا بعد ترحيل يدوي، ثغرة حقيقية اكتُشفت من الاستخدام
        # الفعلي).
        move = self.env['account.move'].sudo().create(move_vals)
        move.action_post()

        Line = self.env['bank.settlement.prepaid.line'].sudo()
        for index, (period_start, period_end, amount) in enumerate(schedule):
            Line.create({
                'res_model': self._name,
                'res_id': self.id,
                'sequence': index + 1,
                'name': '%s/%s' % (self.name, index + 1),
                'employee_id': self.employee_id.id,
                'category_id': category.id,
                'company_id': self.company_id.id,
                'currency_id': self.currency_id.id,
                'period_start_date': period_start,
                'period_end_date': period_end,
                'amount': amount,
            })
        return move.id

    def _get_returnable_stages(self):
        """قائمة مرتبة (من الأقرب للحالة الحالية إلى الأبعد) بأزواج
        (كود الحالة، اسمها المعروض) تمثّل كل المراحل السابقة (غير
        "مسودة") التي يصح اختيارها كوجهة عبر "إرجاع للتصحيح" - بنفس
        مبدأ اختيار المرحلة المستهدفة في recruitment_workflow (حيث
        يختار المستخدم المرحلة صراحة من قائمة، بدل خطوة واحدة ثابتة).
        "مسودة" نفسها ليست ضمن القائمة - "إرجاع للتصحيح" يُبقي أي موافقة
        أسبق من المرحلة المختارة قائمة كما هي، بعكس العودة الكاملة
        لمسودة (كانت أداة منفصلة، أُلغيت عمداً: يُعتمَد فقط على "إرجاع
        للتصحيح" لتصحيح مرحلة واحدة، أو "رفض" لسجل يحتاج بداية جديدة
        بالكامل).

        النماذج الأربعة الأساسية المستخدمة لسلسلة الحالات المشتركة هنا
        (draft -> under_review -> confirmed -> done) لها خيار واحد فقط
        ذو معنى: confirmed -> under_review. advance.py له سلسلة حالات
        مختلفة (5 حالات، وموافقتان منفصلتان) فيُجاوز هذه الدالة بخيارين."""
        self.ensure_one()
        selection = dict(self._fields['state'].selection)
        if self.state == 'confirmed':
            return [('under_review', selection.get('under_review'))]
        return []

    def _get_previous_stage(self):
        """أقرب مرحلة سابقة (أول عنصر في _get_returnable_stages) - تُستخدم
        كقيمة افتراضية عند عدم اختيار مرحلة مستهدفة صراحة."""
        self.ensure_one()
        stages = self._get_returnable_stages()
        return stages[0][0] if stages else False

    def action_open_return_wizard(self):
        """يفتح معالج "إرجاع للتصحيح" (يفرض اختيار المرحلة المستهدفة
        وتسجيل السبب) - الزر في الواجهة يستدعي هذه الدالة بدل
        action_return_to_previous_stage مباشرة، بنفس نمط باقي المعالجات
        أعلاه."""
        self.ensure_one()
        if not self._get_returnable_stages():
            raise UserError('لا توجد مرحلة سابقة يمكن الرجوع إليها من الحالة الحالية.')
        return {
            'name': 'إرجاع للتصحيح',
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def action_return_to_previous_stage(self, target_state=False, reason=False):
        """التراجع الفعلي إلى مرحلة سابقة مختارة (target_state) - أو
        أقرب مرحلة سابقة تلقائياً إن لم تُحدَّد (_get_previous_stage)،
        للتوافق مع الاستدعاء المباشر بلا معالج. تُبقي أي موافقة أسبق من
        المرحلة المختارة قائمة كما هي (مثال: اختيار "وافق مسؤول المشروع"
        في سلفة يُلغي اعتماد المدير العام فقط، ويُبقي موافقة مسؤول
        المشروع سارية). تتطلب صلاحية مدير عام السداد البنكي وسبباً
        إجبارياً، ولا تُستدعى مباشرة من زر بالواجهة - تمر حصراً عبر
        bank.settlement.return.wizard (انظر action_open_return_wizard
        أعلاه)، الذي يقيّد الاختيار فعلياً لقائمة _get_returnable_stages
        فقط (طبقة حماية إضافية من جهة الخادم هنا أيضاً، دفاعاً ضد أي
        استدعاء RPC مباشر بمرحلة غير صالحة)."""
        if not reason:
            raise UserError('يجب توضيح سبب الإرجاع للتصحيح.')
        for rec in self:
            returnable_codes = [code for code, _label in rec._get_returnable_stages()]
            chosen = target_state or (returnable_codes[0] if returnable_codes else False)
            if not chosen or chosen not in returnable_codes:
                raise UserError('لا يمكن الإرجاع لهذه المرحلة من الحالة الحالية.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        for rec in self:
            returnable_codes = [code for code, _label in rec._get_returnable_stages()]
            chosen = target_state or returnable_codes[0]
            old_state_label = dict(rec._fields['state'].selection).get(rec.state, rec.state)
            new_state_label = dict(rec._fields['state'].selection).get(chosen, chosen)
            rec.message_post(
                body='تم إرجاع السجل للتصحيح من "%s" إلى "%s" (مع الحفاظ على '
                     'أي موافقة أسبق للمرحلة المختارة).<br/>السبب: %s'
                     % (old_state_label, new_state_label, reason)
            )
            rec.write({'state': chosen, 'returned_for_correction': True})

    def action_open_reject_wizard(self):
        """يفتح معالج "رفض" (يفرض تسجيل السبب) - الزر في الواجهة يستدعي
        هذه الدالة بدل action_reject مباشرة."""
        self.ensure_one()
        return {
            'name': 'رفض السجل',
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def action_reject(self, reason=False):
        """رفض السجل - يتطلب سبباً إجبارياً. يُستخدم عند اكتشاف محاسب/
        مدير عام السداد البنكي أن بيانات السجل خاطئة جوهرياً (تحتاج
        بداية جديدة بالكامل من مُنشئه، وليس مجرد تصحيح مرحلة واحدة -
        استخدم "إرجاع للتصحيح" لذلك بدلاً منه). لا تُستدعى مباشرة من زر
        بالواجهة - تمر حصراً عبر bank.settlement.reject.wizard الذي
        يفرض تمرير السبب (انظر action_open_reject_wizard أعلاه)، بنفس
        مبدأ "رفض" في recruitment_workflow.recruitment_request.

        يؤرشف السجل تلقائياً (active=False) عند الرفض - طلب صريح: سجل
        مرفوض يخرج من القوائم النشطة الافتراضية (يبقى متاحاً عبر فلتر
        "مؤرشف" المعياري للتدقيق)، بدل البقاء ظاهراً بشكل دائم بحالة
        "مرفوضة" وسط بقية السجلات النشطة."""
        if not reason:
            raise UserError('يجب إدخال سبب الرفض.')
        for rec in self:
            if rec.state in ('done', 'cancel', 'rejected'):
                raise UserError(
                    'لا يمكن رفض سجل بحالة "%s".'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
        for rec in self:
            rec.message_post(body='تم رفض السجل.<br/>السبب: %s' % reason)
        self.write({'state': 'rejected', 'rejection_reason': reason, 'active': False})

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
            # يُستخدم لحصر رؤية "مستخدم/محاسب" السداد البنكي على قيودهم
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
        # sudo(): إنشاء القيد نفسه لا يجب أن يشترط عضوية "مستخدم/محاسب
        # السداد البنكي" في إحدى مجموعات المحاسبة الأصلية بـ Odoo (فوترة،
        # محاسب Odoo نفسه...) - الصلاحية الفعلية لهذا الإجراء محكومة بالفعل عبر
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
