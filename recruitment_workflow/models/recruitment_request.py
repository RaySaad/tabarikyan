# -*- coding: utf-8 -*-
import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class RecruitmentRequest(models.Model):
    _name = 'recruitment.request'
    _description = 'طلب التوظيف'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'recruitment.workflow.analytic.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # الحقول الأساسية
    # ------------------------------------------------------------------
    name = fields.Char(
        string='رقم الطلب',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('جديد'),
        tracking=True,
    )
    employee_name = fields.Char(
        string='اسم الموظف',
        required=True,
        tracking=True,
    )
    identification_id = fields.Char(
        string='رقم الهوية / الإقامة',
        required=True,
        tracking=True,
        help='يجب أن يتكون من 10 أرقام ويبدأ بالرقم 1 أو 2.',
    )
    mobile = fields.Char(
        string='رقم الجوال',
        required=True,
        tracking=True,
        help='رقم جوال سعودي: 05XXXXXXXX أو 9665XXXXXXXX أو +9665XXXXXXXX.',
    )
    email = fields.Char(string='البريد الإلكتروني', required=True, tracking=True)

    # --- بيانات الهوية الموسّعة (حسب البروبوزل) ---
    id_expiry_date = fields.Date(
        string='تاريخ انتهاء الهوية / الإقامة (ميلادي)',
        tracking=True,
    )
    id_expiry_date_hijri = fields.Char(
        string='تاريخ انتهاء الهوية / الإقامة (هجري)',
        compute='_compute_id_expiry_hijri',
        store=True,
        readonly=True,
        help='يُحسب تلقائياً من التاريخ الميلادي.',
    )
    passport_no = fields.Char(string='رقم الجواز', tracking=True)

    # --- البيانات الشخصية (تُربط بسجل الموظف) ---
    country_id = fields.Many2one(
        'res.country', string='الجنسية', tracking=True,
    )
    gender = fields.Selection(
        selection=[
            ('male', 'ذكر'),
            ('female', 'أنثى'),
            ('other', 'أخرى'),
        ],
        string='الجنس',
        tracking=True,
    )
    marital = fields.Selection(
        selection=[
            ('single', 'أعزب'),
            ('married', 'متزوج'),
        ],
        string='الحالة الاجتماعية',
        tracking=True,
    )

    # --- الحساب البنكي ---
    iban = fields.Char(string='رقم الآيبان (IBAN)', tracking=True)
    bank_name = fields.Char(string='اسم البنك')

    # --- العنوان الخاص ---
    street = fields.Char(string='الشارع')
    street2 = fields.Char(string='الشارع 2')
    city = fields.Char(string='المدينة')
    state_address_id = fields.Many2one('res.country.state', string='المنطقة / الولاية')
    zip_code = fields.Char(string='الرمز البريدي')
    address_country_id = fields.Many2one('res.country', string='الدولة')

    # نظام العمل والتطبيق الرئيسي (يحدد في الطلب الجديد)
    compensation_type_id = fields.Many2one(
        'recruitment.compensation.type',
        string='نظام العمل',
        tracking=True,
        help='نظام العمل/الأجر الذي سيعمل به المندوب (بالطلبات، بالعمولة، '
             'راتب ثابت...). تُفلتَر الخيارات المتاحة هنا تلقائياً حسب '
             'المشروع/المنصة المختارة أعلاه.',
    )
    # حقل مساعد (related) فقط لبناء domain حقل compensation_type_id في
    # الواجهة - لا يمكن استخدام project_id.compensation_type_ids مباشرة
    # داخل domain (لا يدعمه محرّك النطاقات في المتصفح لحقول Many2many).
    project_compensation_type_ids = fields.Many2many(
        related='project_id.compensation_type_ids',
        string='أنظمة العمل المتاحة على المنصة',
    )
    main_application = fields.Char(
        string='التطبيق الرئيسي',
        tracking=True,
        help='التطبيق الرئيسي الذي سيعمل عليه الموظف.',
    )

    # الوظيفة والمشروع
    job_id = fields.Many2one('hr.job', string='الوظيفة', tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='القسم', tracking=True,
    )
    project_manager_id = fields.Many2one(
        'res.users',
        string='مسؤول المشروع',
        tracking=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='المشروع / المنصة',
        tracking=True,
        help='المنصة التي سيعمل عليها المندوب (مثال: كيتا، هنقرستيشن). '
             'تُستخدم لفصل المتابعة والحسابات (Analytic Account) لكل منصة، '
             'ولفلترة سيارات الأسطول التابعة لنفس المنصة.',
    )
    # ملاحظة: حقل analytic_account_id يأتي من recruitment.workflow.analytic.mixin
    # (models/recruitment_analytic_mixin.py) ويُحسب تلقائياً من project_id.

    # ------------------------------------------------------------------
    # رسوم التوظيف (مرحلة "تم السداد") - تُرفع كفاتورة مورد حقيقية
    # ------------------------------------------------------------------
    fee_cost_type_id = fields.Many2one(
        'hr.employee.cost.type',
        string='نوع الرسوم',
        tracking=True,
        help='نوع الرسوم المطلوب سدادها (تأشيرة، رسوم توظيف، إلخ) - يحدد '
             'الحساب المحاسبي ودفتر اليومية المستخدم عند إصدار الفاتورة.',
    )
    fee_partner_id = fields.Many2one(
        'res.partner',
        string='الجهة المستفيدة (المورّد)',
        tracking=True,
        help='الجهة التي ستُصدَر لها فاتورة المورد (مكتب استقدام، جهة حكومية...).',
    )
    fee_amount = fields.Monetary(string='مبلغ الرسوم', currency_field='currency_id', tracking=True)
    fee_move_id = fields.Many2one(
        'account.move',
        string='فاتورة الرسوم',
        readonly=True,
        copy=False,
    )
    fee_payment_state = fields.Selection(
        related='fee_move_id.payment_state',
        string='حالة سداد الرسوم',
        readonly=True,
    )

    # الحالة والمرحلة
    stage_id = fields.Many2one(
        'recruitment.stage',
        string='المرحلة',
        group_expand='_read_group_stage_ids',
        tracking=True,
        copy=False,
        index=True,
        default=lambda self: self._default_stage_id(),
    )
    stage_code = fields.Char(related='stage_id.code', string='رمز المرحلة', store=True)
    state = fields.Selection(
        selection=[
            ('in_progress', 'قيد التنفيذ'),
            ('done', 'مكتمل'),
            ('rejected', 'مرفوض'),
        ],
        string='الحالة',
        default='in_progress',
        tracking=True,
        copy=False,
    )
    rejection_reason = fields.Text(string='سبب الرفض', tracking=True, copy=False)

    # المرفقات
    attachment_line_ids = fields.One2many(
        'recruitment.request.attachment',
        'request_id',
        string='المرفقات',
        copy=False,
    )
    attachments_complete = fields.Boolean(
        string='المرفقات مكتملة',
        compute='_compute_attachments_complete',
        store=True,
    )
    attachment_progress = fields.Float(
        string='نسبة اكتمال المرفقات',
        compute='_compute_attachments_complete',
        store=True,
    )

    # الأسطول / السيارة
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='السيارة المخصصة',
        tracking=True,
        copy=False,
        domain="[('recruitment_state', '=', 'available')]",
    )
    car_requested = fields.Boolean(
        string='تم طلب سيارة',
        tracking=True,
        copy=False,
    )
    car_request_state = fields.Selection(
        selection=[
            ('none', 'لا يوجد طلب'),
            ('requested', 'تم إرسال الطلب للأسطول'),
            ('received', 'تم استلام الطلب من الأسطول'),
            ('authorized', 'تم التفويض'),
        ],
        string='حالة طلب السيارة',
        default='none',
        tracking=True,
        copy=False,
    )

    # العقد
    # ملاحظة: نموذج hr.contract غير موجود في Community (خاص بـ Payroll/Enterprise).
    # نستخدم حقل Reference بدلاً من Many2one حتى لا يفشل تحميل الموديول
    # عندما تكون وحدة العقود غير مثبتة، مع الحفاظ على إمكانية الربط عند توفرها.
    contract_ref = fields.Reference(
        selection='_selection_contract_model',
        string='العقد',
        readonly=True,
        copy=False,
    )
    contract_id_int = fields.Integer(
        string='معرّف العقد',
        readonly=True,
        copy=False,
        help='معرّف رقمي للعقد المرتبط (للاستخدام الداخلي).',
    )
    has_contract = fields.Boolean(
        string='يوجد عقد',
        compute='_compute_has_contract',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='الموظف (سجل HR)',
        readonly=True,
        copy=False,
    )
    contract_start_date = fields.Date(
        string='تاريخ بدء العقد',
        default=fields.Date.context_today,
    )
    wage = fields.Monetary(string='الراتب', currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='العملة',
        default=lambda self: self.env.company.currency_id,
    )

    company_id = fields.Many2one(
        'res.company',
        string='الشركة',
        default=lambda self: self.env.company,
    )
    color = fields.Integer(string='اللون')
    active = fields.Boolean(string='نشط', default=True)

    # ------------------------------------------------------------------
    # الافتراضيات
    # ------------------------------------------------------------------
    @api.model
    def _default_stage_id(self):
        return self.env['recruitment.stage'].search(
            [('code', '=', 'new')], limit=1,
        ) or self.env['recruitment.stage'].search([], order='sequence', limit=1)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['recruitment.stage'].search([], order='sequence')

    # ------------------------------------------------------------------
    # التعبئة التلقائية عند اختيار المشروع/المنصة
    # ------------------------------------------------------------------
    @api.onchange('project_id')
    def _onchange_project_id(self):
        """يقترح مسؤول المشروع (من project.project.user_id) والوظيفة
        والقسم (من الوظيفة الافتراضية المضبوطة على المنصة) تلقائياً عند
        اختيار المشروع - تبقى قابلة للتعديل يدوياً بعد ذلك."""
        # نظام العمل مرتبط بالمنصة (domain في الواجهة) - إن كان النظام
        # المختار سابقاً غير متاح على المنصة الجديدة (أو أُفرغ المشروع)
        # نفرغه حتى لا يبقى محتفظاً بقيمة لم تعد صالحة. وإن كانت المنصة
        # تدعم نظاماً واحداً فقط، نقترحه تلقائياً.
        available_compensation = self.project_id.compensation_type_ids
        if self.compensation_type_id and self.compensation_type_id not in available_compensation:
            self.compensation_type_id = False
        if len(available_compensation) == 1:
            self.compensation_type_id = available_compensation

        if not self.project_id:
            return
        if self.project_id.user_id:
            self.project_manager_id = self.project_id.user_id
        if self.project_id.default_job_id:
            self.job_id = self.project_id.default_job_id
            self.department_id = self.project_id.default_job_id.department_id

    # ------------------------------------------------------------------
    # الحسابات
    # ------------------------------------------------------------------
    @api.depends('attachment_line_ids.file', 'attachment_line_ids.required')
    def _compute_attachments_complete(self):
        for rec in self:
            required_lines = rec.attachment_line_ids.filtered('required')
            if not required_lines:
                rec.attachments_complete = True
                rec.attachment_progress = 100.0
                continue
            uploaded = required_lines.filtered(lambda l: bool(l.file))
            rec.attachment_progress = (len(uploaded) / len(required_lines)) * 100.0
            rec.attachments_complete = len(uploaded) == len(required_lines)

    @api.depends('id_expiry_date')
    def _compute_id_expiry_hijri(self):
        """تحويل تاريخ الانتهاء الميلادي إلى هجري.

        يستخدم خوارزمية حسابية مدمجة (تقويم إسلامي مدني/جدولي) لا تحتاج
        أي مكتبة خارجية، فتعمل مباشرة على أي خادم.
        """
        for rec in self:
            if not rec.id_expiry_date:
                rec.id_expiry_date_hijri = False
                continue
            try:
                hy, hm, hd = self._gregorian_to_hijri(
                    rec.id_expiry_date.year,
                    rec.id_expiry_date.month,
                    rec.id_expiry_date.day,
                )
                months = [
                    'محرم', 'صفر', 'ربيع الأول', 'ربيع الآخر',
                    'جمادى الأولى', 'جمادى الآخرة', 'رجب', 'شعبان',
                    'رمضان', 'شوال', 'ذو القعدة', 'ذو الحجة',
                ]
                rec.id_expiry_date_hijri = '%d %s %d هـ' % (
                    hd, months[hm - 1], hy,
                )
            except Exception:
                rec.id_expiry_date_hijri = False

    @staticmethod
    def _gregorian_to_hijri(gy, gm, gd):
        """تحويل تاريخ ميلادي إلى هجري (تقويم إسلامي جدولي).

        خوارزمية قياسية تعتمد على الأيام اليوليانية (Julian Day Number)،
        دقيقة بفارق يوم واحد كحد أقصى عن رؤية الهلال الفعلية.
        """
        # ميلادي -> اليوم اليولياني
        a = (14 - gm) // 12
        y = gy + 4800 - a
        m = gm + 12 * a - 3
        jdn = (gd + (153 * m + 2) // 5 + 365 * y + y // 4
               - y // 100 + y // 400 - 32045)
        # اليوم اليولياني -> هجري
        l = jdn - 1948440 + 10632
        n = (l - 1) // 10631
        l = l - 10631 * n + 354
        j = ((10985 - l) // 5316) * ((50 * l) // 17719) \
            + (l // 5670) * ((43 * l) // 15238)
        l = (l - ((30 - j) // 15) * ((17719 * j) // 50)
             - (j // 16) * ((15238 * j) // 43) + 29)
        hm = (24 * l) // 709
        hd = l - (709 * hm) // 24
        hy = 30 * n + j - 30
        return hy, hm, hd

    def action_recompute_hijri(self):
        """زر لإعادة حساب التاريخ الهجري يدوياً."""
        self._compute_id_expiry_hijri()
        return True

    # ------------------------------------------------------------------
    # التحقق من القيود (الكنترول)
    # ------------------------------------------------------------------
    @api.constrains('identification_id')
    def _check_identification_id(self):
        for rec in self:
            if not rec.identification_id:
                continue
            value = rec.identification_id.strip()
            if not value.isdigit():
                raise ValidationError(_(
                    'رقم الهوية يجب أن يحتوي على أرقام فقط.'
                ))
            if len(value) != 10:
                raise ValidationError(_(
                    'رقم الهوية يجب أن يتكون من 10 أرقام بالضبط (تم إدخال %s رقم).'
                ) % len(value))
            if value[0] not in ('1', '2'):
                raise ValidationError(_(
                    'رقم الهوية يجب أن يبدأ بالرقم 1 (مواطن) أو 2 (مقيم).'
                ))

    @api.constrains('mobile')
    def _check_mobile(self):
        # التصنيف السعودي: 05XXXXXXXX | 9665XXXXXXXX | +9665XXXXXXXX
        pattern = re.compile(r'^(?:(?:\+?966)|0)5\d{8}$')
        for rec in self:
            if not rec.mobile:
                continue
            value = rec.mobile.strip().replace(' ', '').replace('-', '')
            if not pattern.match(value):
                raise ValidationError(_(
                    'رقم الجوال غير صالح. يجب أن يكون رقم جوال سعودي صحيح '
                    'يبدأ بـ 05 أو 9665 أو +9665 ويتكون من العدد الصحيح من الأرقام.'
                ))

    _sql_constraints = [
        (
            'identification_uniq',
            'unique(identification_id, company_id)',
            'يوجد طلب توظيف آخر بنفس رقم الهوية في هذه الشركة!',
        ),
    ]

    def _check_duplicate_employee(self):
        """فحص تكرار رقم الهوية ضد سجلات الموظفين الحالية.

        حسب البروبوزل: يُفحص ضد hr.employee.identification_id و
        l10n_sa_employee_code (إن وُجد حقل الكود السعودي).
        """
        self.ensure_one()
        if not self.identification_id:
            return
        Employee = self.env['hr.employee'].sudo()
        emp_fields = Employee._fields
        domain = ['|', ('identification_id', '=', self.identification_id)]
        if 'l10n_sa_employee_code' in emp_fields:
            domain.append(('l10n_sa_employee_code', '=', self.identification_id))
        else:
            # إزالة عامل OR الزائد إن لم يوجد الحقل الثاني
            domain = [('identification_id', '=', self.identification_id)]
        existing = Employee.search(domain, limit=1)
        if existing:
            raise UserError(_(
                'يوجد موظف مسجّل بالفعل بنفس رقم الهوية (%(id)s): %(emp)s.\n'
                'لا يمكن متابعة الطلب لتفادي التكرار.'
            ) % {'id': self.identification_id, 'emp': existing.name})

    # ------------------------------------------------------------------
    # إنشاء السجل
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'recruitment.request'
                ) or _('جديد')
        records = super().create(vals_list)
        for rec in records:
            rec._populate_attachment_lines()
        return records

    def _populate_attachment_lines(self):
        """تعبئة سطور المرفقات من أنواع المرفقات المفعّلة."""
        self.ensure_one()
        if self.attachment_line_ids:
            return
        types = self.env['recruitment.attachment.type'].search([])
        lines = [(0, 0, {
            'attachment_type_id': t.id,
            'sequence': t.sequence,
        }) for t in types]
        if lines:
            self.attachment_line_ids = lines

    # ------------------------------------------------------------------
    # منطق الانتقال بين المراحل
    # ------------------------------------------------------------------
    def _get_stage_by_code(self, code):
        return self.env['recruitment.stage'].search([('code', '=', code)], limit=1)

    def _next_stage(self):
        self.ensure_one()
        stages = self.env['recruitment.stage'].search([], order='sequence')
        stage_ids = stages.ids
        if self.stage_id.id in stage_ids:
            idx = stage_ids.index(self.stage_id.id)
            if idx + 1 < len(stage_ids):
                return stages[idx + 1]
        return False

    def _validate_stage_exit(self, current_stage):
        """التحقق من شروط الخروج من المرحلة الحالية قبل الانتقال."""
        self.ensure_one()
        if current_stage.require_attachments and not self.attachments_complete:
            missing = self.attachment_line_ids.filtered(
                lambda l: l.required and not l.file
            ).mapped('attachment_type_id.name')
            raise UserError(_(
                'لا يمكن الانتقال للمرحلة التالية. المرفقات الإجبارية غير مكتملة.\n'
                'المرفقات الناقصة:\n- %s'
            ) % '\n- '.join(missing))

        # فحص تكرار الموظف عند الخروج من المرحلة الأولى (الطلب الجديد)
        if current_stage.code == 'new':
            self._check_duplicate_employee()

        if current_stage.require_project and not self.project_id:
            raise UserError(_(
                'لا يمكن الانتقال للمرحلة التالية. يجب تحديد المشروع/المنصة '
                '(مثال: كيتا، هنقرستيشن) التي سيعمل عليها المندوب أولاً.'
            ))

        # نضمن وجود حساب تحليلي على المشروع المختار هنا بالذات - هذه اللحظة
        # التي يحتاج فيها موديول التوظيف فعلياً لفصل المتابعة والحسابات،
        # وليس عند إنشاء أي مشروع آخر بالنظام لا علاقة له بالتوظيف.
        if current_stage.require_project and self.project_id and not self.project_id.account_id:
            self.project_id._create_default_analytic_account()

        # مرحلة "تم السداد": التحقق الفعلي من سداد فاتورة الرسوم من المحاسبة
        # (وليس مجرد تأكيد يدوي) - يمنع تجاوز الفحص عبر Kanban/API أيضاً.
        if current_stage.code == 'paid':
            if not self.fee_move_id:
                raise UserError(_(
                    'لا يمكن الانتقال للمرحلة التالية. يجب إصدار فاتورة '
                    'الرسوم أولاً (زر "إصدار فاتورة الرسوم").'
                ))
            if self.fee_move_id.payment_state not in ('paid', 'in_payment'):
                raise UserError(_(
                    'لا يمكن الانتقال للمرحلة التالية. فاتورة الرسوم لم تُسدَّد بعد.\n'
                    'يجب أن يعتمد فريق المحاسبة الفاتورة ويسجّل الدفعة من '
                    'تطبيق المحاسبة أولاً.'
                ))

        if current_stage.require_car:
            if not self.vehicle_id:
                raise UserError(_(
                    'لا يمكن الانتقال للمرحلة التالية. يجب تخصيص سيارة متاحة من الأسطول.\n'
                    'في حال عدم توفر سيارة لا يمكن متابعة الطلب.'
                ))
            if self.car_request_state != 'authorized':
                raise UserError(_(
                    'لا يمكن الانتقال للمرحلة التالية. طلب السيارة لم يُعتمد بعد.\n'
                    'يجب أن يوافق مسؤول الأسطول على الطلب (تفويض السيارة) أولاً.'
                ))

    def action_next_stage(self):
        for rec in self:
            rec._validate_stage_exit(rec.stage_id)
            next_stage = rec._next_stage()
            if not next_stage:
                raise UserError(_('هذه هي المرحلة الأخيرة، لا توجد مرحلة تالية.'))
            rec._on_enter_stage(next_stage)
        return True

    def write(self, vals):
        # عند تغيير المرحلة يدوياً (Kanban drag & drop، شريط الحالة القابل
        # للنقر، أو أي استدعاء write() مباشر عبر RPC) نسمح فقط بالانتقال
        # خطوة واحدة للأمام (المرحلة التالية مباشرة)، مع التحقق من شروط
        # الخروج وصلاحية الموافقة على تلك الخطوة. القفز عدة مراحل دفعة واحدة
        # ممنوع تماماً - حتى لو كانت كل الشروط الوسيطة مستوفاة وامتلك
        # المستخدم كل الصلاحيات - لضمان مرور كل موافقة كحدث منفصل موثّق.
        # أما الإرجاع لمرحلة سابقة فممنوع بالكامل عبر هذا المسار: يجب أن يمر
        # حصراً عبر معالج "إرجاع للتصحيح" (action_return_to_stage).
        if 'stage_id' in vals and not self.env.context.get('skip_stage_validation'):
            new_stage = self.env['recruitment.stage'].browse(vals['stage_id'])
            for rec in self:
                if not rec.stage_id or new_stage == rec.stage_id:
                    continue
                if new_stage.sequence > rec.stage_id.sequence:
                    # نمنع القفز أكثر من مرحلة واحدة دفعة واحدة (مثلاً بالضغط
                    # على فقاعة متقدمة في شريط الحالة القابل للنقر) - حتى لو
                    # كانت كل الشروط الوسيطة مستوفاة تقنياً. الانتقال يجب أن
                    # يمر خطوة بخطوة عبر الأزرار الصريحة (موافقة/الانتقال
                    # للمرحلة التالية) لضمان تسجيل كل موافقة كحدث منفصل.
                    if new_stage != rec._next_stage():
                        raise UserError(_(
                            'لا يمكن القفز عدة مراحل دفعة واحدة.\n'
                            'استخدم أزرار الموافقة/الانتقال للمرحلة التالية '
                            'للتنقل خطوة بخطوة.'
                        ))
                    rec._validate_stage_exit(rec.stage_id)
                    rec._check_approval_rights(rec.stage_id)
                else:
                    # الإرجاع لمرحلة سابقة (مثلاً بالضغط على فقاعة سابقة في
                    # شريط الحالة القابل للنقر) مسموح فقط عبر معالج "إرجاع
                    # للتصحيح" (action_return_to_stage) الذي يفرض تسجيل سبب
                    # الإرجاع وإشعار المسؤولين - وليس بنقرة مباشرة تتجاوز ذلك.
                    raise UserError(_(
                        'لا يمكن إرجاع الطلب لمرحلة سابقة بهذه الطريقة.\n'
                        'استخدم زر "إرجاع للتصحيح" لتسجيل سبب الإرجاع.'
                    ))
        res = super().write(vals)
        if 'stage_id' in vals:
            for rec in self:
                rec._apply_stage_side_effects()
        return res

    def _on_enter_stage(self, stage):
        self.ensure_one()
        self.stage_id = stage.id  # write() سيطبق التحقق والآثار الجانبية

    def _apply_stage_side_effects(self):
        """تطبيق الآثار الجانبية عند دخول مرحلة معينة."""
        self.ensure_one()
        # أنهِ أي نشاط (Activity) سابق متعلق بهذا الطلب - المرحلة تغيّرت
        # فالإجراء المطلوب سابقاً لم يعد ذا قيمة.
        self.activity_ids.action_feedback(feedback=_('انتقل الطلب لمرحلة أخرى'))

        code = self.stage_id.code or ''
        if code == 'started':
            # تم مباشرة العمل => إنشاء عقد أوتوماتيك
            self._create_contract()
            self.state = 'done'
        elif self.stage_id.is_closing_stage:
            self.state = 'done'

        # جدولة إشعار (Activity) لصاحب القرار بالمرحلة الجديدة - بحيث يصله
        # تنبيه بأي تطبيق فاتحه (Accounting/Fleet/إلخ) بدون ما يحتاج يتصفح
        # موديول التوظيف بنفسه للانتباه إن فيه شيء ينتظره.
        self._schedule_stage_activity()

    # ------------------------------------------------------------------
    # إشعارات تلقائية (Activities) لأصحاب القرار حسب المرحلة/الحدث
    # ------------------------------------------------------------------
    _STAGE_RESPONSIBLE_GROUP = {
        'project_review': ('recruitment_workflow.group_recruitment_workflow_project_manager',
                            'مطلوب مراجعتك: طلب توظيف جديد بانتظار مراجعة مسؤول المشروع'),
        'operations_review': ('recruitment_workflow.group_recruitment_workflow_operations',
                               'مطلوب مراجعتك: طلب توظيف بانتظار مراجعة مدير العمليات'),
        'gm_approval': ('recruitment_workflow.group_recruitment_workflow_gm',
                         'مطلوب اعتمادك: طلب توظيف بانتظار اعتماد المدير العام'),
    }

    def _schedule_activity_for_group(self, group_xmlid, summary, note=False):
        """يجدول نشاط (Activity) لأول مستخدم بالمجموعة المحددة. لا يفشل لو
        المجموعة أو المستخدمون غير موجودين (بيئة إعداد ناقصة)."""
        self.ensure_one()
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        # all_user_ids يشمل المستخدمين المنضمين مباشرة والمستخدمين الذين
        # يملكون هذه الصلاحية عبر التوارث (implied_ids) - مثلاً مدير سير
        # العمل يجب أن يصله إشعار مهمة "مدير العمليات" حتى لو لم يُضَف
        # صراحة لمجموعة مدير العمليات.
        if not group or not group.all_user_ids:
            return
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=summary,
            note=note or '',
            user_id=group.all_user_ids[0].id,
        )

    def _schedule_stage_activity(self):
        self.ensure_one()
        entry = self._STAGE_RESPONSIBLE_GROUP.get(self.stage_id.code or '')
        if not entry:
            return
        group_xmlid, summary = entry
        self._schedule_activity_for_group(
            group_xmlid, summary,
            note=_('الطلب: %s - المندوب: %s') % (self.name, self.employee_name or ''),
        )

    # ------------------------------------------------------------------
    # الموافقة / الرفض
    # ------------------------------------------------------------------
    # خريطة المرحلة ← المجموعة المخوّلة بالموافقة عليها
    _STAGE_APPROVAL_GROUP = {
        'project_review': 'recruitment_workflow.group_recruitment_workflow_project_manager',
        'operations_review': 'recruitment_workflow.group_recruitment_workflow_operations',
        'gm_approval': 'recruitment_workflow.group_recruitment_workflow_gm',
        # إنهاء مرحلة "طلب سيارة" (بعد تفويض الأسطول) مخصّص لمسؤول المشروع
        # فقط - يطابق تقييد زر "إنهاء طلب السيارة والمتابعة" في الواجهة.
        'car_request': 'recruitment_workflow.group_recruitment_workflow_project_manager',
    }

    # المراحل التي يجب أن يوافق عليها الشخص المعيّن تحديداً على هذا الطلب
    # (حقل مسؤول المشروع الخاص بالمشروع/المنصة نفسها) - وليس أي عضو آخر في
    # مجموعة "مسؤول المشروع"، حتى لو كان مديراً عاماً أو مديراً كامل
    # الصلاحيات. إن لم يكن الحقل معيّناً بعد، يُكتفى بالتحقق من المجموعة.
    _STAGE_ASSIGNED_USER_FIELD = {
        'project_review': 'project_manager_id',
        'car_request': 'project_manager_id',
    }

    def _check_approval_rights(self, stage=None):
        """التحقق من أن المستخدم الحالي مخوّل بالموافقة على المرحلة المحددة
        (المرحلة الحالية افتراضياً).

        طبقة حماية ثانية بعد إخفاء الأزرار في الواجهة، تمنع تجاوز الصلاحية
        عبر استدعاء الدالة مباشرة أو الكتابة المباشرة على stage_id (RPC/API).
        """
        self.ensure_one()
        stage = stage or self.stage_id
        group_xmlid = self._STAGE_APPROVAL_GROUP.get(stage.code or '')
        if not group_xmlid:
            return  # مرحلة غير تقييمية، لا قيد

        assigned_field = self._STAGE_ASSIGNED_USER_FIELD.get(stage.code or '')
        assigned_user = self[assigned_field] if assigned_field else False
        if assigned_user:
            if self.env.user != assigned_user:
                raise UserError(_(
                    'ليست لديك الصلاحية للموافقة على هذه المرحلة (%(stage)s).\n'
                    'هذه المرحلة تتطلب موافقة "%(assignee)s" تحديداً (مسؤول '
                    'المشروع المعيّن على هذا الطلب).'
                ) % {'stage': stage.name, 'assignee': assigned_user.name})
            return

        # لا يوجد شخص معيّن بعد لهذه المرحلة - نكتفي بالتحقق من المجموعة
        # (المدير العام والمدير الكامل يملكان الصلاحية عبر التوارث)
        if not self.env.user.has_group(group_xmlid):
            raise UserError(_(
                'ليست لديك الصلاحية للموافقة على هذه المرحلة (%s).\n'
                'هذه المرحلة تتطلب صلاحية المستوى المناسب.'
            ) % stage.name)

    def _check_group(self, *group_xmlids):
        """يتحقق أن المستخدم الحالي ضمن إحدى المجموعات المحددة. طبقة حماية
        من جهة الخادم للأفعال الحساسة، لا تعتمد فقط على إخفاء الأزرار في
        الواجهة (والتي يمكن تجاوزها عبر RPC/API مباشرة)."""
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    def _send_stage_mail(self, template_xmlid):
        """يرسل قالب البريد المحدد للمرشّح إن كان بريده الإلكتروني معروفاً.
        لا يفشل الإجراء الأساسي (موافقة/رفض) إن تعذّر الإرسال."""
        self.ensure_one()
        if not self.email:
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return
        template.send_mail(self.id, force_send=False)

    def action_approve(self):
        """موافقة على المرحلة الحالية والانتقال للتالية."""
        for rec in self:
            rec._check_approval_rights()
            rec.message_post(
                body=_('تمت الموافقة على المرحلة: %s') % rec.stage_id.name,
            )
            rec.action_next_stage()
            rec._send_stage_mail('recruitment_workflow.mail_template_request_approved')
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'name': _('رفض الطلب'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_open_return_wizard(self):
        """فتح مساعد الإرجاع لمرحلة سابقة للتصحيح."""
        self.ensure_one()
        if self.stage_id.sequence <= self.env['recruitment.stage'].search(
            [], order='sequence', limit=1,
        ).sequence:
            raise UserError(_(
                'هذا الطلب في المرحلة الأولى، لا توجد مرحلة سابقة للإرجاع إليها.'
            ))
        return {
            'name': _('إرجاع للتصحيح'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_return_to_stage(self, target_stage, reason):
        """إرجاع الطلب لمرحلة سابقة مع تسجيل السبب وإشعار المسؤولين.

        الطلب يبقى حياً (لا أرشفة)؛ فقط يعود خطوة/خطوات للتصحيح.
        """
        self.ensure_one()
        old_stage = self.stage_id
        # السماح بالكتابة رغم أن الوجهة مرحلة سابقة (نتجاوز فحص الانتقال للأمام)
        self.with_context(skip_stage_validation=True).write({
            'stage_id': target_stage.id,
        })
        # إعادة الحالة لقيد التنفيذ إن كانت مرفوضة
        if self.state == 'rejected':
            self.state = 'in_progress'
        self.message_post(
            body=_(
                'تم إرجاع الطلب من مرحلة "%(from)s" إلى مرحلة "%(to)s" للتصحيح.\n'
                'السبب: %(reason)s'
            ) % {
                'from': old_stage.name,
                'to': target_stage.name,
                'reason': reason,
            },
            subtype_xmlid='mail.mt_comment',
        )
        return True

    def action_reject(self, reason=None):
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
            rec.write({
                'state': 'rejected',
                'rejection_reason': reason or rec.rejection_reason,
            })
            rec.message_post(
                body=_('تم رفض الطلب في مرحلة %(stage)s. السبب: %(reason)s') % {
                    'stage': rec.stage_id.name,
                    'reason': reason or _('غير محدد'),
                },
            )
            # تحرير السيارة المخصصة عند الرفض
            rec._release_vehicle()
            rec._send_stage_mail('recruitment_workflow.mail_template_request_rejected')
            # أرشفة الطلب المرفوض (يختفي من القائمة النشطة)
            rec.active = False
        return True

    def action_reset_to_draft(self):
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
            rec.with_context(skip_stage_validation=True).write({
                'state': 'in_progress',
                'rejection_reason': False,
                'stage_id': rec._default_stage_id().id,
                'active': True,  # إعادة تفعيله من الأرشيف
            })
            rec.message_post(body=_('تمت إعادة تفعيل الطلب من الأرشيف وإرجاعه للبداية.'))
        return True

    def action_unarchive_request(self):
        """إعادة تفعيل الطلب المؤرشف دون تغيير مرحلته."""
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
            rec.active = True
            rec.message_post(body=_('تمت إعادة الطلب من الأرشيف.'))
        return True

    # ------------------------------------------------------------------
    # رسوم التوظيف - إصدار فاتورة مورد حقيقية بدل تأكيد يدوي
    # ------------------------------------------------------------------
    @api.onchange('fee_cost_type_id')
    def _onchange_fee_cost_type_id(self):
        if self.fee_cost_type_id and self.fee_cost_type_id.partner_id and not self.fee_partner_id:
            self.fee_partner_id = self.fee_cost_type_id.partner_id

    def action_create_fee_bill(self):
        """يصدر فاتورة مورد (Vendor Bill) بمبلغ رسوم التوظيف، موزّعة تحليلياً
        على مشروع/منصة الطلب. من هذه اللحظة، اعتماد الفاتورة وسدادها تصير
        مسؤولية فريق المحاسبة بالكامل من داخل تطبيق المحاسبة (Accounting)،
        دون أي حاجة للرجوع لموديول التوظيف."""
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
            if rec.fee_move_id:
                raise UserError(_('تم إصدار فاتورة الرسوم لهذا الطلب من قبل.'))
            if not rec.fee_amount or rec.fee_amount <= 0:
                raise UserError(_('حدد مبلغ الرسوم قبل إصدار الفاتورة.'))
            if not rec.fee_cost_type_id:
                raise UserError(_('حدد نوع الرسوم قبل إصدار الفاتورة.'))
            if not rec.fee_partner_id:
                raise UserError(_('حدد الجهة المستفيدة (المورّد) قبل إصدار الفاتورة.'))
            if not rec.project_id:
                raise UserError(_('حدد المشروع/المنصة أولاً.'))
            if not rec.project_id.account_id:
                rec.project_id._create_default_analytic_account()

            distribution = {}
            if rec.analytic_account_id:
                distribution = {str(rec.analytic_account_id.id): 100.0}

            line_fields = self.env['account.move.line']._fields
            line_vals = {
                'name': _('رسوم %s - %s') % (rec.fee_cost_type_id.name, rec.employee_name or rec.name),
                'quantity': 1.0,
                'price_unit': rec.fee_amount,
            }
            if rec.fee_cost_type_id.expense_account_id and 'account_id' in line_fields:
                line_vals['account_id'] = rec.fee_cost_type_id.expense_account_id.id
            if 'analytic_distribution' in line_fields and distribution:
                line_vals['analytic_distribution'] = distribution
            elif 'analytic_account_id' in line_fields and rec.analytic_account_id:
                line_vals['analytic_account_id'] = rec.analytic_account_id.id

            move_vals = {
                'move_type': 'in_invoice',
                'partner_id': rec.fee_partner_id.id,
                'invoice_date': fields.Date.context_today(rec),
                'ref': _('رسوم توظيف - %s') % rec.name,
                'company_id': rec.company_id.id if 'company_id' in rec._fields else self.env.company.id,
                'invoice_line_ids': [(0, 0, line_vals)],
            }
            if rec.fee_cost_type_id.journal_id:
                move_vals['journal_id'] = rec.fee_cost_type_id.journal_id.id

            move = self.env['account.move'].sudo().create(move_vals)
            rec.fee_move_id = move.id
            rec.message_post(body=_(
                'تم إصدار فاتورة رسوم %(move)s (مسودة) لفريق المحاسبة لمراجعتها '
                'واعتمادها وسدادها من تطبيق المحاسبة مباشرة.'
            ) % {'move': move.display_name})
            rec._schedule_activity_for_group(
                'recruitment_workflow.group_recruitment_workflow_accountant',
                'مطلوب منك: فاتورة رسوم توظيف بانتظار المراجعة والسداد',
                note=_('الطلب: %s - المبلغ: %s') % (rec.name, rec.fee_amount),
            )

    def action_view_fee_bill(self):
        self.ensure_one()
        self._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        if not self.fee_move_id:
            raise UserError(_('لا يوجد فاتورة رسوم مرتبطة بعد.'))
        return {
            'name': _('فاتورة الرسوم'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.fee_move_id.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # منطق طلب السيارة (التكامل مع الأسطول)
    # ------------------------------------------------------------------
    def action_send_car_request(self):
        """إرسال طلب سيارة لقسم الأسطول - مسؤول المشروع يطلب سيارة فقط، ولا
        يختار سيارة محدَّدة؛ اختيار السيارة تحديداً مسؤولية قسم الأسطول عند
        الاستلام/التفويض (انظر action_fleet_authorize)."""
        self.ensure_one()
        self._check_group('recruitment_workflow.group_recruitment_workflow_project_manager')
        domain = [('recruitment_state', '=', 'available')]
        if self.project_id:
            domain += ['|', ('project_id', '=', self.project_id.id), ('project_id', '=', False)]
        if not self.env['fleet.vehicle'].search_count(domain):
            raise UserError(_(
                'لا توجد سيارات متاحة في الأسطول حالياً (لنفس المنصة أو بدون منصة محددة). '
                'لا يمكن متابعة الطلب حتى تتوفر سيارة.'
            ))
        self.write({
            'car_requested': True,
            'car_request_state': 'requested',
        })
        self.message_post(body=_('تم إرسال طلب سيارة إلى قسم الأسطول.'))
        self._schedule_activity_for_group(
            'recruitment_workflow.group_recruitment_workflow_fleet',
            'مطلوب منك: طلب سيارة جديد بانتظار الاستلام والتخصيص',
            note=_('الطلب: %s') % self.name,
        )

    def action_fleet_receive(self):
        """قسم الأسطول يستلم الطلب."""
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_fleet')
            if rec.car_request_state != 'requested':
                raise UserError(_('لا يوجد طلب سيارة بانتظار الاستلام.'))
            rec.car_request_state = 'received'
            rec.message_post(body=_('تم استلام طلب السيارة من قسم الأسطول.'))

    def action_fleet_authorize(self):
        """قسم الأسطول يختار السيارة المحدَّدة (حقل vehicle_id) ثم يفوّضها
        => يعود الطلب لمسؤول المشروع."""
        for rec in self:
            rec._check_group('recruitment_workflow.group_recruitment_workflow_fleet')
            if rec.car_request_state != 'received':
                raise UserError(_('يجب استلام الطلب أولاً قبل التفويض.'))
            if not rec.vehicle_id:
                raise UserError(_('يجب اختيار سيارة متاحة قبل التفويض.'))
            rec.car_request_state = 'authorized'
            rec.vehicle_id.write({'recruitment_state': 'assigned'})
            # نربط السيارة بالمرشّح كـ"سائق مستقبلي" (حقل Fleet القياسي) فور
            # التفويض مباشرة - وليس فقط عند إنشاء سجل الموظف لاحقاً - حتى
            # تظهر السيارة محجوزة بوضوح داخل تطبيق Fleet نفسه من هذه اللحظة.
            candidate_partner = rec._get_or_create_candidate_partner()
            if candidate_partner:
                rec.vehicle_id.sudo().future_driver_id = candidate_partner.id
            rec.message_post(body=_(
                'تم تفويض السيارة. الطلب الآن لدى مسؤول المشروع للمتابعة.'
            ))

    def _get_or_create_candidate_partner(self):
        """يوجد أو ينشئ partner خفيف يمثّل المرشّح قبل إنشاء سجل الموظف
        الرسمي - يُستخدم لربطه كـ"سائق مستقبلي" على السيارة فور التفويض
        (Fleet)، ثم يُعاد استخدامه لاحقاً كجهة اتصال العمل الرسمية للموظف
        بدل إنشاء partner مكرر (انظر _create_employee)."""
        self.ensure_one()
        if self.vehicle_id.future_driver_id:
            return self.vehicle_id.future_driver_id
        if self.vehicle_id.driver_id:
            return self.vehicle_id.driver_id
        Partner = self.env['res.partner'].sudo()
        partner_fields = Partner._fields
        # ملاحظة: لا نضبط type='private' - هذه القيمة لم تعد موجودة ضمن
        # خيارات res.partner.type في أودو 19 (تبقى contact/invoice/
        # delivery/other فقط)؛ الافتراضي 'contact' مناسب هنا.
        partner_vals = {'name': self.employee_name}
        # الحقل mobile حُذف من res.partner في أودو 19 (بقي phone فقط) - نتحقق
        # قبل الكتابة بدل افتراض وجوده، بنفس أسلوب set_if المستخدم في بقية
        # الموديول للتعامل مع اختلاف الحقول بين الإصدارات.
        if 'mobile' in partner_fields:
            partner_vals['mobile'] = self.mobile
        elif 'phone' in partner_fields:
            partner_vals['phone'] = self.mobile
        if self.email and 'email' in partner_fields:
            partner_vals['email'] = self.email
        return Partner.create(partner_vals)

    def _release_vehicle(self):
        self.ensure_one()
        if self.vehicle_id and self.vehicle_id.recruitment_state in ('reserved', 'assigned'):
            # نُفرغ حقلي السائق/السائق المستقبلي القياسيين أيضاً - وإلا بقيت
            # السيارة تظهر "محجوزة" لهذا المرشّح في تطبيق Fleet رغم رفض طلبه.
            self.vehicle_id.sudo().write({
                'recruitment_state': 'available',
                'future_driver_id': False,
                'driver_id': False,
            })

    # ------------------------------------------------------------------
    # إنشاء العقد الأوتوماتيكي
    # ------------------------------------------------------------------
    def _create_employee(self):
        """إنشاء سجل الموظف في الموارد البشرية إن لم يكن موجوداً.

        يطبّق خريطة الحقول الموسّعة حسب البروبوزل، ويضيف كل حقل فقط
        إن كان موجوداً في نموذج hr.employee (اعتماد مرن مع التخصيصات).
        """
        self.ensure_one()
        if self.employee_id:
            return self.employee_id

        Employee = self.env['hr.employee'].sudo()
        emp_fields = Employee._fields

        employee_vals = {'name': self.employee_name}

        def set_if(field_name, value):
            if value and field_name in emp_fields:
                employee_vals[field_name] = value

        # إعادة استخدام partner "السائق المستقبلي" الذي رُبط بالسيارة عند
        # التفويض (action_fleet_authorize) كجهة اتصال العمل الرسمية للموظف
        # الجديد - بدل إنشاء partner مكرر له.
        if self.vehicle_id and self.vehicle_id.future_driver_id:
            set_if('work_contact_id', self.vehicle_id.future_driver_id.id)

        set_if('mobile_phone', self.mobile)
        set_if('work_email', self.email)
        set_if('job_id', self.job_id.id)
        set_if('department_id', self.department_id.id)
        set_if('company_id', self.company_id.id)
        set_if('identification_id', self.identification_id)
        # كود الموظف السعودي إن وُجد (l10n_sa)
        set_if('l10n_sa_employee_code', self.identification_id)
        # المشروع/المنصة (كيتا، هنقرستيشن...) - يُضبط أيضاً بعد الإنشاء عبر
        # _set_platform لضمان فتح سجل تاريخي (platform history) صحيح
        set_if('project_id', self.project_id.id)
        set_if('country_id', self.country_id.id)
        # الحقل أُعيدت تسميته من gender إلى sex في نواة hr منذ Odoo 19 -
        # نجرّب الاسمين حتى يعمل على أي إصدار/تخصيص محتمل يستخدم الاسم القديم.
        set_if('gender', self.gender)
        set_if('sex', self.gender)
        set_if('marital', self.marital)
        set_if('passport_id', self.passport_no)
        # العنوان الخاص
        set_if('private_street', self.street)
        set_if('private_street2', self.street2)
        set_if('private_city', self.city)
        set_if('private_state_id', self.state_address_id.id)
        set_if('private_zip', self.zip_code)
        set_if('private_country_id', self.address_country_id.id)

        employee = Employee.create(employee_vals)
        self.employee_id = employee.id

        # فتح أول سطر في سجل تاريخ المنصات للموظف (إن كان الحقل متوفراً، أي أن
        # موديول ربط المنصات مُثبّت)
        if self.project_id and 'project_id' in emp_fields \
                and hasattr(employee, '_open_platform_history'):
            employee._open_platform_history(
                self.project_id,
                note=_('فتح تلقائي عند مباشرة العمل من طلب التوظيف %s') % self.name,
            )

        # ترقية "السائق المستقبلي" إلى "السائق" الفعلي على السيارة (حقلا
        # Fleet القياسيان) الآن بعد أن باشر العمل فعلياً - وليس فقط منذ لحظة
        # التفويض. driver_id هو ما تعرضه واجهات Fleet نفسها (بخلاف حقلنا
        # المخصَّص recruitment_state المستخدَم داخلياً فقط لفلترة التوفر).
        if self.vehicle_id:
            driver_partner = self.vehicle_id.future_driver_id or self._get_employee_partner(employee)
            if driver_partner:
                self.vehicle_id.sudo().write({
                    'driver_id': driver_partner.id,
                    'future_driver_id': False,
                })

        # ربط الحساب البنكي (IBAN) إن وُجد - محاط بحماية حتى لا يفشل الإنشاء
        try:
            self._create_employee_bank_account(employee)
        except Exception:
            self.message_post(body=_(
                'تم إنشاء الموظف لكن تعذّر ربط الحساب البنكي تلقائياً. '
                'يُرجى إضافة الآيبان يدوياً في سجل الموظف.'
            ))
        return employee

    def _get_employee_partner(self, employee):
        """يحاول إيجاد partner الموظف الشخصي (لربط حساب بنكي أو تخصيص سيارة
        كسائق) بعدة طرق احتياطية حسب ما هو متوفر في نظامك."""
        emp_fields = employee._fields
        if 'work_contact_id' in emp_fields and employee.work_contact_id:
            return employee.work_contact_id
        if 'address_home_id' in emp_fields and employee.address_home_id:
            return employee.address_home_id
        if employee.user_id and employee.user_id.partner_id:
            return employee.user_id.partner_id
        return False

    def _create_employee_bank_account(self, employee):
        """إنشاء/ربط حساب بنكي (res.partner.bank) بالموظف من الآيبان."""
        self.ensure_one()
        if not self.iban:
            return False
        emp_fields = employee._fields
        partner = self._get_employee_partner(employee)

        if not partner:
            partner = self.env['res.partner'].sudo().create({
                'name': self.employee_name,
            })
            if 'work_contact_id' in emp_fields:
                employee.work_contact_id = partner.id
            elif 'address_home_id' in emp_fields:
                employee.address_home_id = partner.id

        Bank = self.env['res.partner.bank'].sudo()
        existing = Bank.search([
            ('acc_number', '=', self.iban),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if existing:
            return existing
        bank_vals = {
            'acc_number': self.iban,
            'partner_id': partner.id,
        }
        if self.bank_name and 'bank_name' in Bank._fields:
            bank_vals['bank_name'] = self.bank_name
        return Bank.create(bank_vals)

    def _get_contract_model_name(self):
        """تحديد اسم نموذج العقد المتاح وقت التشغيل.

        - om_hr_payroll (Community): يقدّم نموذج 'hr.contract'.
        - Odoo 19 القياسي/Enterprise: أعاد تسمية العقد إلى 'hr.version'.
        نرجّح hr.contract لتوافق om_hr_payroll المثبّت، ثم hr.version.
        """
        for model_name in ('hr.contract', 'hr.version'):
            if model_name in self.env:
                return model_name
        return False

    def _create_contract(self):
        """إنشاء العقد أوتوماتيكياً.

        اعتماد مرن يكتشف نموذج العقد المتاح وقت التشغيل:
        'hr.contract' (om_hr_payroll) أو 'hr.version' (Odoo 19 القياسي).
        إن لم يتوفر أي منهما نكتفي بإنشاء سجل الموظف وتسجيل ملاحظة دون خطأ.
        """
        self.ensure_one()
        if self.contract_ref:
            return self.contract_ref

        employee = self._create_employee()

        model_name = self._get_contract_model_name()
        if not model_name:
            self.message_post(body=_(
                'تم إنشاء سجل الموظف %s. لم يُعثر على نموذج عقد (Payroll) على هذا '
                'النظام، لذا لم يُنشأ عقد تلقائي. يمكن تثبيت وحدة العقود/الرواتب '
                'لتفعيل الإنشاء التلقائي للعقود.'
            ) % self.employee_name)
            return False

        Contract = self.env[model_name].sudo()
        contract_fields = Contract._fields

        contract_vals = {}
        # اسم العقد: قد يكون الحقل name أو contract_reference حسب الإصدار
        if 'name' in contract_fields:
            contract_vals['name'] = _('عقد - %s') % self.employee_name
        if 'employee_id' in contract_fields:
            contract_vals['employee_id'] = employee.id
        # wage حقل مطلوب في om_hr_payroll؛ نضمن قيمة غير سالبة
        if 'wage' in contract_fields:
            contract_vals['wage'] = self.wage or 0.0
        if 'date_start' in contract_fields:
            contract_vals['date_start'] = (
                self.contract_start_date or fields.Date.context_today(self)
            )
        if 'contract_date_start' in contract_fields:
            contract_vals['contract_date_start'] = (
                self.contract_start_date or fields.Date.context_today(self)
            )
        if 'company_id' in contract_fields:
            contract_vals['company_id'] = self.company_id.id
        if self.job_id and 'job_id' in contract_fields:
            contract_vals['job_id'] = self.job_id.id
        if self.department_id and 'department_id' in contract_fields:
            contract_vals['department_id'] = self.department_id.id
        # ربط المشروع/المنصة والحساب التحليلي بالعقد إن كانت الحقول متوفرة
        # (تختلف تسمية الحقل التحليلي حسب النسخة/التخصيص المثبت: الحقل
        # الحديث analytic_distribution، أو Many2one قديم analytic_account_id/account_id)
        if self.project_id and 'project_id' in contract_fields:
            contract_vals['project_id'] = self.project_id.id
        if self.analytic_account_id:
            if 'analytic_distribution' in contract_fields:
                contract_vals['analytic_distribution'] = {
                    str(self.analytic_account_id.id): 100.0,
                }
            else:
                for analytic_field in ('analytic_account_id', 'account_id'):
                    if analytic_field in contract_fields:
                        contract_vals[analytic_field] = self.analytic_account_id.id
                        break

        # ساعات العمل (resource_calendar_id) - حقل إجباري في hr.version بـ Odoo 19
        if 'resource_calendar_id' in contract_fields:
            calendar = False
            if self.department_id and 'resource_calendar_id' in self.department_id._fields:
                calendar = self.department_id.resource_calendar_id
            if not calendar:
                calendar = self.company_id.resource_calendar_id \
                    if 'resource_calendar_id' in self.company_id._fields else False
            if not calendar:
                calendar = self.env['resource.calendar'].sudo().search(
                    [('company_id', 'in', [self.company_id.id, False])], limit=1,
                )
            if calendar:
                contract_vals['resource_calendar_id'] = calendar.id

        # مصدر إدخالات العمل (إجباري في hr.version) - نضبطه على جدول العمل
        if 'work_entry_source' in contract_fields:
            we_field = contract_fields['work_entry_source']
            we_sel = we_field.selection
            if callable(we_sel):
                we_sel = we_sel(Contract)
            we_keys = [k for k, _v in (we_sel or [])]
            if 'calendar' in we_keys:
                contract_vals['work_entry_source'] = 'calendar'
            elif we_keys:
                contract_vals['work_entry_source'] = we_keys[0]

        # حالة العقد: 'open' = ساري (موجودة في om_hr_payroll؛ قد لا توجد في hr.version)
        if 'state' in contract_fields:
            state_field = contract_fields['state']
            valid = dict(state_field.selection or []) if hasattr(state_field, 'selection') else {}
            if not valid or 'open' in valid:
                contract_vals['state'] = 'open'
        # الهيكل الراتبي إن وُجد (اختياري)
        if 'struct_id' in contract_fields and 'hr.payroll.structure' in self.env:
            struct = self.env['hr.payroll.structure'].sudo().search([], limit=1)
            if struct:
                contract_vals['struct_id'] = struct.id

        # تعبئة أي حقول إجبارية أخرى لم تُملأ بعد، بقيم افتراضية آمنة،
        # لضمان نجاح إنشاء العقد في أي إصدار/تخصيص (hr.version في Odoo 19 له
        # حقول إجبارية إضافية مثل ساعات العمل ونوع العقد).
        contract_vals = self._fill_required_contract_fields(
            Contract, contract_vals,
        )

        contract = False
        if model_name == 'hr.version':
            # في Odoo 19 يُنشأ للموظف إصدار (version) تلقائياً عند إنشائه.
            # لا يُسمح بإصدارين مفعّلين بنفس تاريخ السريان، لذا نحدّث الإصدار
            # الحالي للموظف بدل إنشاء واحد جديد.
            existing_version = self._get_employee_current_version(employee)
            if existing_version:
                # نكتب فقط القيم التي أدخلها المستخدم فعلاً، ونترك الحقول
                # التي ملأها النظام تلقائياً (ساعات العمل، نوع العقد...) كما هي.
                vf = existing_version._fields
                update_vals = {}
                if 'wage' in vf:
                    update_vals['wage'] = self.wage or 0.0
                if self.job_id and 'job_id' in vf:
                    update_vals['job_id'] = self.job_id.id
                if self.department_id and 'department_id' in vf:
                    update_vals['department_id'] = self.department_id.id
                start = self.contract_start_date or fields.Date.context_today(self)
                if 'contract_date_start' in vf:
                    update_vals['contract_date_start'] = start
                elif 'date_start' in vf:
                    update_vals['date_start'] = start
                if update_vals:
                    existing_version.write(update_vals)
                contract = existing_version
        if not contract:
            contract = Contract.create(contract_vals)

        self.contract_ref = '%s,%s' % (model_name, contract.id)
        self.contract_id_int = contract.id
        self.message_post(
            body=_('تم إنشاء/تحديث العقد %s أوتوماتيكياً وربطه بالموظف %s.') % (
                contract.display_name, self.employee_name,
            ),
        )
        return contract

    def _get_employee_current_version(self, employee):
        """إيجاد الإصدار الحالي (hr.version) للموظف في Odoo 19."""
        emp_fields = employee._fields
        for fname in ('current_version_id', 'version_id'):
            if fname in emp_fields and employee[fname]:
                return employee[fname].sudo()
        # بحث احتياطي مباشر في hr.version
        if 'hr.version' in self.env:
            version = self.env['hr.version'].sudo().search(
                [('employee_id', '=', employee.id)],
                order='date_version desc', limit=1,
            )
            return version
        return False

    def _fill_required_contract_fields(self, Contract, vals):
        """يكتشف الحقول الإجبارية غير المملوءة ويضع لها قيماً افتراضية آمنة.

        يتعامل مع الأنواع الشائعة: many2one (أول سجل متاح)، selection (أول
        خيار)، تواريخ (اليوم)، أرقام (0)، نصوص (شرطة). يتجاهل الحقول المحسوبة
        والمرتبطة وغير المخزّنة.
        """
        self.ensure_one()
        defaults = Contract.default_get(list(Contract._fields.keys()))
        for fname, field in Contract._fields.items():
            if fname in vals:
                continue
            if not getattr(field, 'required', False):
                continue
            # تجاهل الحقول المحسوبة/المرتبطة (تُملأ تلقائياً)
            if field.compute or field.related:
                continue
            # إن كان للحقل قيمة افتراضية من النظام، نتركها
            if defaults.get(fname) not in (None, False):
                continue
            ftype = field.type
            try:
                if ftype == 'many2one':
                    rec = self.env[field.comodel_name].sudo().search([], limit=1)
                    if rec:
                        vals[fname] = rec.id
                elif ftype in ('selection',):
                    sel = field.selection
                    if callable(sel):
                        sel = sel(Contract)
                    if sel:
                        vals[fname] = sel[0][0]
                elif ftype in ('date',):
                    vals[fname] = fields.Date.context_today(self)
                elif ftype in ('datetime',):
                    vals[fname] = fields.Datetime.now()
                elif ftype in ('integer', 'float', 'monetary'):
                    vals[fname] = 0
                elif ftype in ('char', 'text'):
                    vals[fname] = '-'
                elif ftype == 'boolean':
                    vals[fname] = False
            except Exception:
                # في حال تعذّر إيجاد قيمة، نتجاهل ونترك Odoo يتعامل معها
                continue
        return vals

    def action_view_contract(self):
        self.ensure_one()
        self._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        if not self.contract_ref:
            raise UserError(_('لا يوجد عقد مرتبط بهذا الطلب.'))
        return {
            'name': _('العقد'),
            'type': 'ir.actions.act_window',
            'res_model': self.contract_ref._name,
            'res_id': self.contract_ref.id,
            'view_mode': 'form',
        }

    @api.model
    def _selection_contract_model(self):
        """خيارات حقل Reference: نماذج العقود المتوفرة فقط."""
        options = []
        if 'hr.contract' in self.env:
            options.append(('hr.contract', _('عقد عمل')))
        if 'hr.version' in self.env:
            options.append(('hr.version', _('إصدار العقد')))
        return options

    @api.depends('contract_ref')
    def _compute_has_contract(self):
        for rec in self:
            rec.has_contract = bool(rec.contract_ref)
