# -*- coding: utf-8 -*-
import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class RecruitmentRequest(models.Model):
    _name = 'recruitment.request'
    _description = 'طلب التوظيف'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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

    # نظام التشغيل والتطبيق الرئيسي (يحدد في الطلب الجديد)
    operating_system = fields.Selection(
        selection=[
            ('windows', 'Windows'),
            ('macos', 'macOS'),
            ('linux', 'Linux'),
            ('android', 'Android'),
            ('ios', 'iOS'),
        ],
        string='نظام التشغيل',
        tracking=True,
        help='يحدده الموظف في الطلب الجديد.',
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
            ('draft', 'مسودة'),
            ('in_progress', 'قيد التنفيذ'),
            ('done', 'مكتمل'),
            ('rejected', 'مرفوض'),
        ],
        string='الحالة',
        default='draft',
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
    wage = fields.Monetary(string='الراتب', currency_field='currency_id')
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
            if vals.get('state', 'draft') == 'draft':
                vals['state'] = 'in_progress'
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

        if current_stage.require_car and not self.vehicle_id:
            raise UserError(_(
                'لا يمكن الانتقال للمرحلة التالية. يجب تخصيص سيارة متاحة من الأسطول.\n'
                'في حال عدم توفر سيارة لا يمكن متابعة الطلب.'
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
        # عند تغيير المرحلة يدوياً (Kanban drag & drop) نتحقق من الشروط
        if 'stage_id' in vals and not self.env.context.get('skip_stage_validation'):
            new_stage = self.env['recruitment.stage'].browse(vals['stage_id'])
            for rec in self:
                if rec.stage_id and new_stage.sequence > rec.stage_id.sequence:
                    rec._validate_stage_exit(rec.stage_id)
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
        code = self.stage_id.code or ''
        if code == 'started':
            # تم مباشرة العمل => إنشاء عقد أوتوماتيك
            self._create_contract()
            self.state = 'done'
        elif self.stage_id.is_closing_stage:
            self.state = 'done'

    # ------------------------------------------------------------------
    # الموافقة / الرفض
    # ------------------------------------------------------------------
    # خريطة المرحلة ← المجموعة المخوّلة بالموافقة عليها
    _STAGE_APPROVAL_GROUP = {
        'project_review': 'recruitment_workflow.group_recruitment_workflow_project_manager',
        'operations_review': 'recruitment_workflow.group_recruitment_workflow_operations',
        'gm_approval': 'recruitment_workflow.group_recruitment_workflow_gm',
    }

    def _check_approval_rights(self):
        """التحقق من أن المستخدم الحالي مخوّل بالموافقة على المرحلة الحالية.

        طبقة حماية ثانية بعد إخفاء الأزرار في الواجهة، تمنع تجاوز الصلاحية
        عبر استدعاء الدالة مباشرة (RPC/API).
        """
        self.ensure_one()
        group_xmlid = self._STAGE_APPROVAL_GROUP.get(self.stage_id.code or '')
        if not group_xmlid:
            return  # مرحلة غير تقييمية، لا قيد
        # المدير العام والمدير الكامل يملكان الصلاحية عبر التوارث
        if not self.env.user.has_group(group_xmlid):
            raise UserError(_(
                'ليست لديك الصلاحية للموافقة على هذه المرحلة (%s).\n'
                'هذه المرحلة تتطلب صلاحية المستوى المناسب.'
            ) % self.stage_id.name)

    def action_approve(self):
        """موافقة على المرحلة الحالية والانتقال للتالية."""
        for rec in self:
            rec._check_approval_rights()
            rec.message_post(
                body=_('تمت الموافقة على المرحلة: %s') % rec.stage_id.name,
            )
            rec.action_next_stage()
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
            # أرشفة الطلب المرفوض (يختفي من القائمة النشطة)
            rec.active = False
        return True

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({
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
            rec.active = True
            rec.message_post(body=_('تمت إعادة الطلب من الأرشيف.'))
        return True

    # ------------------------------------------------------------------
    # منطق طلب السيارة (التكامل مع الأسطول)
    # ------------------------------------------------------------------
    def action_open_car_request_wizard(self):
        self.ensure_one()
        available = self.env['fleet.vehicle'].search_count(
            [('recruitment_state', '=', 'available')]
        )
        if not available:
            raise UserError(_(
                'لا توجد سيارات متاحة في الأسطول حالياً. '
                'لا يمكن متابعة الطلب حتى تتوفر سيارة.'
            ))
        return {
            'name': _('طلب سيارة'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.request.car.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_send_car_request(self, vehicle):
        """إرسال طلب السيارة لقسم الأسطول."""
        self.ensure_one()
        self.write({
            'vehicle_id': vehicle.id,
            'car_requested': True,
            'car_request_state': 'requested',
        })
        vehicle.write({'recruitment_state': 'reserved'})
        self.message_post(
            body=_('تم إرسال طلب السيارة %s إلى قسم الأسطول.') % vehicle.display_name,
        )

    def action_fleet_receive(self):
        """قسم الأسطول يستلم الطلب."""
        for rec in self:
            if rec.car_request_state != 'requested':
                raise UserError(_('لا يوجد طلب سيارة بانتظار الاستلام.'))
            rec.car_request_state = 'received'
            rec.message_post(body=_('تم استلام طلب السيارة من قسم الأسطول.'))

    def action_fleet_authorize(self):
        """قسم الأسطول يفوّض الطلب => يعود الطلب لمسؤول المشروع."""
        for rec in self:
            if rec.car_request_state != 'received':
                raise UserError(_('يجب استلام الطلب أولاً قبل التفويض.'))
            rec.car_request_state = 'authorized'
            rec.vehicle_id.write({'recruitment_state': 'assigned'})
            rec.message_post(body=_(
                'تم تفويض السيارة. الطلب الآن لدى مسؤول المشروع للمتابعة.'
            ))

    def _release_vehicle(self):
        self.ensure_one()
        if self.vehicle_id and self.vehicle_id.recruitment_state in ('reserved', 'assigned'):
            self.vehicle_id.write({'recruitment_state': 'available'})

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

        set_if('mobile_phone', self.mobile)
        set_if('work_email', self.email)
        set_if('job_id', self.job_id.id)
        set_if('department_id', self.department_id.id)
        set_if('company_id', self.company_id.id)
        set_if('identification_id', self.identification_id)
        # كود الموظف السعودي إن وُجد (l10n_sa)
        set_if('l10n_sa_employee_code', self.identification_id)
        set_if('country_id', self.country_id.id)
        set_if('gender', self.gender)
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

        # ربط الحساب البنكي (IBAN) إن وُجد - محاط بحماية حتى لا يفشل الإنشاء
        try:
            self._create_employee_bank_account(employee)
        except Exception:
            self.message_post(body=_(
                'تم إنشاء الموظف لكن تعذّر ربط الحساب البنكي تلقائياً. '
                'يُرجى إضافة الآيبان يدوياً في سجل الموظف.'
            ))
        return employee

    def _create_employee_bank_account(self, employee):
        """إنشاء/ربط حساب بنكي (res.partner.bank) بالموظف من الآيبان."""
        self.ensure_one()
        if not self.iban:
            return False
        emp_fields = employee._fields
        partner = False
        if 'work_contact_id' in emp_fields and employee.work_contact_id:
            partner = employee.work_contact_id
        elif 'address_home_id' in emp_fields and employee.address_home_id:
            partner = employee.address_home_id
        elif employee.user_id and employee.user_id.partner_id:
            partner = employee.user_id.partner_id

        if not partner:
            partner = self.env['res.partner'].sudo().create({
                'name': self.employee_name,
                'type': 'private',
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
