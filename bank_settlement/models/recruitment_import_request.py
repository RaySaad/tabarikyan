# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class RecruitmentImportRequest(models.Model):
    """طلب استقدام: مسار مستقل عن طلب التوظيف (recruitment.request) عمداً -
    طلب صريح: "اريد ان يكون منفصل وليس في طلب التوظيف لانه سيحصل تداخل
    وممكن تحصل مشكلة". يبدأ برقم الطلب وتسجيل الرسوم الحكومية، وبعد تأكيد
    سدادها (عبر السداد البنكي - الرسوم نفسها تمر بنفس دورة الموافقة
    المعتادة هناك) تُدخَل بيانات الموظف الأساسية فقط، فيُنشأ سجل الموظف
    وتُربَط الرسوم به فوراً، ويُنشأ تلقائياً طلب توظيف (recruitment.request)
    بعلم is_import_request - بقية المسار (مراجعة مسؤول المشروع، المرفقات،
    اعتماد المدير العام، استلام السيارة) يكمل من هناك بلا أي تكرار لواجهة
    إدخال البيانات، ودون المرور بمراحل نقل الكفالة (لا معنى لها هنا: الموظف
    يُستقدَم من الخارج، وليس منقولاً من كفيل آخر).

    هذا النموذج مُعرَّف بالكامل في bank_settlement (وليس recruitment_workflow)
    لنفس السبب الموجود في recruitment_request.py من هذا الموديول: يحتاج
    الربط المباشر بـbank.settlement.government.fee، وrecruitment_workflow
    لا يعتمد على bank_settlement (والعكس فقط هو الصحيح تقنياً).
    """
    _name = 'recruitment.import.request'
    _description = 'طلب استقدام'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='رقم الطلب', required=True, copy=False, readonly=True,
        index=True, default=lambda self: _('جديد'), tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('fee_registered', 'بانتظار سداد الرسوم'),
            ('fee_paid', 'تم سداد الرسوم - إدخال بيانات الموظف'),
            ('done', 'مكتمل - تحوّل لطلب توظيف'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', tracking=True, copy=False,
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )
    active = fields.Boolean(string='نشط', default=True)
    notes = fields.Text(string='ملاحظات')

    # -- الرسوم الحكومية ----------------------------------------------------
    government_entity_id = fields.Many2one(
        'bank.settlement.government.entity', string='الجهة الحكومية',
        required=True, tracking=True,
    )
    fee_type_id = fields.Many2one(
        'bank.settlement.government.fee.type', string='نوع الرسوم',
        required=True, tracking=True,
    )
    gov_fee_amount = fields.Monetary(
        string='مبلغ الرسوم الحكومية', currency_field='currency_id',
        required=True, tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    candidate_partner_id = fields.Many2one(
        'res.partner', string='جهة اتصال المرشّح', readonly=True, copy=False,
        help='جهة اتصال خفيفة تُنشأ فور تسجيل الرسوم الحكومية (لا يوجد '
             'سجل موظف رسمي بعد) - يُعاد اسمها لاحقاً باسم الموظف الفعلي '
             'عند إدخال بياناته، ثم تُستخدم كجهة اتصال عمله الرسمية.',
    )
    bank_settlement_gov_fee_id = fields.Many2one(
        'bank.settlement.government.fee', string='سجل الرسوم الحكومية',
        readonly=True, copy=False,
    )
    bank_settlement_gov_fee_state = fields.Selection(
        related='bank_settlement_gov_fee_id.state', string='حالة سداد الرسوم',
        readonly=True,
    )

    # -- بيانات الموظف الأساسية (تُدخَل بعد سداد الرسوم فقط) ----------------
    employee_name = fields.Char(string='اسم الموظف', tracking=True)
    identification_id = fields.Char(
        string='رقم الهوية / الإقامة', tracking=True,
        help='يجب أن يتكون من 10 أرقام ويبدأ بالرقم 1 أو 2.',
    )
    mobile = fields.Char(
        string='رقم الجوال', tracking=True,
        help='رقم جوال سعودي: 05XXXXXXXX أو 9665XXXXXXXX أو +9665XXXXXXXX.',
    )
    email = fields.Char(string='البريد الإلكتروني', tracking=True)

    employee_id = fields.Many2one(
        'hr.employee', string='الموظف (سجل HR)', readonly=True, copy=False,
        ondelete='restrict',
    )
    recruitment_request_id = fields.Many2one(
        'recruitment.request', string='طلب التوظيف الناتج',
        readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    # التحقق - نفس قواعد recruitment.request.identification_id/mobile
    # بالضبط (مكرَّرة عمداً بدل mixin مشترك - بلا أي تعقيد بنيوي إضافي،
    # حسب طلب صريح بعدم إضافة تعقيدات كبيرة للكود).
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

    def _check_duplicate_employee(self):
        """فحص تكرار رقم الهوية ضد سجلات الموظفين الحالية - نفس منطق
        recruitment.request._check_duplicate_employee بالضبط (مكرَّر
        عمداً، بنفس مبرر الدوال أعلاه)."""
        self.ensure_one()
        if not self.identification_id:
            return
        Employee = self.env['hr.employee'].sudo().with_context(active_test=False)
        emp_fields = Employee._fields
        domain = ['|', ('identification_id', '=', self.identification_id)]
        if 'l10n_sa_employee_code' in emp_fields:
            domain.append(('l10n_sa_employee_code', '=', self.identification_id))
        else:
            domain = [('identification_id', '=', self.identification_id)]
        existing = Employee.search(domain, limit=1)
        if existing:
            raise UserError(_(
                'يوجد موظف مسجّل بالفعل بنفس رقم الهوية (%(id)s): %(emp)s.\n'
                'لا يمكن متابعة الطلب لتفادي التكرار.'
            ) % {'id': self.identification_id, 'emp': existing.name})

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'recruitment.import.request'
                ) or _('جديد')
        return super().create(vals_list)

    def unlink(self):
        # نفس فلسفة recruitment.request.unlink()/bank_settlement_mixin.
        # unlink(): سجل تدقيق دائم بعد مغادرة "مسودة"، فيما عدا "ملغى" -
        # حالة نهائية بلا أثر مالي/سداد فعلي، يحتاج تنظيفها من القوائم.
        for rec in self:
            if rec.state not in ('draft', 'cancel'):
                raise UserError(_(
                    'لا يمكن حذف هذا السجل نهائياً بعد مغادرة "مسودة" إلا '
                    'إن كان "ملغى". استخدم "إلغاء" بدلاً من ذلك إن احتجت '
                    'إيقافه.'
                ))
        return super().unlink()

    # ------------------------------------------------------------------
    # الانتقالات
    # ------------------------------------------------------------------
    def action_register_gov_fee(self):
        """ينشئ سجل "رسوم حكومية" فعلي في السداد البنكي - يمر بنفس دورة
        الموافقة المعتادة هناك (مسودة -> تحت المراجعة -> مؤكدة -> منفّذة)
        بمعزل تام عن حالة "طلب استقدام" نفسها؛ هذا النموذج يكتفي بمراقبة
        حالتها عبر bank_settlement_gov_fee_state."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('لا يمكن تسجيل الرسوم إلا من حالة "مسودة".'))
            if rec.gov_fee_amount <= 0:
                raise UserError(_('يجب تحديد مبلغ الرسوم الحكومية أولاً.'))
            partner = rec._get_or_create_candidate_partner()
            gov_fee = self.env['bank.settlement.government.fee'].sudo().create({
                'government_entity_id': rec.government_entity_id.id,
                'fee_type_id': rec.fee_type_id.id,
                'amount': rec.gov_fee_amount,
                'partner_id': partner.id,
                'company_id': rec.company_id.id,
                'transfer_date': fields.Date.context_today(rec),
            })
            rec.bank_settlement_gov_fee_id = gov_fee.id
            rec.state = 'fee_registered'
            rec.message_post(body=_(
                'تم تسجيل سجل الرسوم الحكومية %s في السداد البنكي - '
                'يُتابَع اعتماده وسداده من هناك.'
            ) % gov_fee.name)

    def action_confirm_fee_paid(self):
        """تأكيد سداد الرسوم فعلياً - يُشترط اكتمال سجل الرسوم الحكومية
        (حالة "منفّذة") من السداد البنكي أولاً، ثم تظهر حقول بيانات
        الموظف الأساسية لإكمال الطلب."""
        for rec in self:
            if rec.state != 'fee_registered':
                raise UserError(_(
                    'لا يمكن تأكيد السداد قبل تسجيل الرسوم الحكومية أولاً.'
                ))
            if not rec.bank_settlement_gov_fee_id \
                    or rec.bank_settlement_gov_fee_id.state != 'done':
                raise UserError(_(
                    'لم يُؤكَّد سداد الرسوم الحكومية بعد من السداد البنكي '
                    '(%s) - يجب إتمامه من هناك أولاً.'
                ) % (rec.bank_settlement_gov_fee_id.name or ''))
            rec.state = 'fee_paid'
            rec.message_post(body=_(
                'تم تأكيد سداد الرسوم الحكومية. يمكن الآن إدخال بيانات الموظف.'
            ))

    def action_create_employee_and_request(self):
        """ينشئ سجل الموظف الرسمي، يربط الرسوم الحكومية به، وينشئ طلب
        توظيف تلقائياً (بعلم is_import_request) يبدأ من مرحلة "طلب جديد" -
        بقية المسار (مرفقات، مراجعات، سيارة) يكمل من هناك بالكامل."""
        for rec in self:
            if rec.state != 'fee_paid':
                raise UserError(_(
                    'لا يمكن إنشاء سجل الموظف قبل تأكيد سداد الرسوم أولاً.'
                ))
            missing = [
                label for field_name, label in (
                    ('employee_name', 'اسم الموظف'),
                    ('identification_id', 'رقم الهوية / الإقامة'),
                    ('mobile', 'رقم الجوال'),
                    ('email', 'البريد الإلكتروني'),
                ) if not rec[field_name]
            ]
            if missing:
                raise UserError(_(
                    'يجب إدخال بيانات الموظف الأساسية أولاً. الحقول '
                    'الناقصة:\n- %s'
                ) % '\n- '.join(missing))
            rec._check_duplicate_employee()
            rec._create_employee_and_request()

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'لا يمكن إلغاء طلب اكتمل بالفعل وتحوّل لطلب توظيف '
                    '(%s).'
                ) % rec.recruitment_request_id.name)
            rec.state = 'cancel'

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('لا يمكن إرجاع طلب مكتمل إلى "مسودة".'))
            rec.state = 'draft'

    def action_view_gov_fee(self):
        self.ensure_one()
        if not self.bank_settlement_gov_fee_id:
            raise UserError(_('لا يوجد سجل رسوم حكومية مرتبط بعد.'))
        return {
            'name': _('سجل الرسوم الحكومية'),
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.government.fee',
            'res_id': self.bank_settlement_gov_fee_id.id,
            'view_mode': 'form',
        }

    def action_view_recruitment_request(self):
        self.ensure_one()
        if not self.recruitment_request_id:
            raise UserError(_('لا يوجد طلب توظيف مرتبط بعد.'))
        return {
            'name': _('طلب التوظيف'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.request',
            'res_id': self.recruitment_request_id.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    def _get_or_create_candidate_partner(self):
        """يوجد أو ينشئ جهة اتصال خفيفة تمثّل المرشّح - نفس مبدأ
        recruitment.request._get_or_create_candidate_partner لكن بمعزل
        عن سياق طلب توظيف (لا يوجد بعد وقت تسجيل الرسوم)."""
        self.ensure_one()
        if self.candidate_partner_id:
            return self.candidate_partner_id
        Partner = self.env['res.partner'].sudo()
        partner_fields = Partner._fields
        partner_vals = {'name': self.employee_name or self.name}
        if 'mobile' in partner_fields:
            partner_vals['mobile'] = self.mobile
        elif 'phone' in partner_fields:
            partner_vals['phone'] = self.mobile
        if self.email and 'email' in partner_fields:
            partner_vals['email'] = self.email
        self.candidate_partner_id = Partner.create(partner_vals).id
        return self.candidate_partner_id

    def _create_employee_and_request(self):
        self.ensure_one()
        employee_name = self.employee_name
        if self.identification_id:
            employee_name = '%s|%s' % (employee_name, self.identification_id)

        partner = self._get_or_create_candidate_partner()
        if partner.name != employee_name:
            partner.sudo().name = employee_name

        Employee = self.env['hr.employee'].sudo()
        emp_fields = Employee._fields

        def set_if(vals, field_name, value):
            if value and field_name in emp_fields:
                vals[field_name] = value

        employee_vals = {'name': employee_name}
        set_if(employee_vals, 'work_contact_id', partner.id)
        set_if(employee_vals, 'mobile_phone', self.mobile)
        set_if(employee_vals, 'work_email', self.email)
        set_if(employee_vals, 'company_id', self.company_id.id)
        set_if(employee_vals, 'identification_id', self.identification_id)
        set_if(employee_vals, 'l10n_sa_employee_code', self.identification_id)

        employee = Employee.create(employee_vals)
        self.employee_id = employee.id

        if self.bank_settlement_gov_fee_id and not self.bank_settlement_gov_fee_id.employee_id:
            self.bank_settlement_gov_fee_id.with_context(
                bank_settlement_skip_approval_lock=True,
            ).write({
                'employee_id': employee.id,
                'partner_id': employee._get_personal_partner().id,
            })

        new_stage = self.env['recruitment.stage'].search([('code', '=', 'new')], limit=1)
        request = self.env['recruitment.request'].create({
            'employee_name': self.employee_name,
            'identification_id': self.identification_id,
            'mobile': self.mobile,
            'email': self.email,
            'employee_id': employee.id,
            'is_import_request': True,
            'stage_id': new_stage.id,
            'gov_fee_amount': self.gov_fee_amount,
            'gov_fee_settled': True,
            'bank_settlement_gov_fee_id': self.bank_settlement_gov_fee_id.id,
            'company_id': self.company_id.id,
            'import_request_id': self.id,
        })
        if self.bank_settlement_gov_fee_id:
            self.bank_settlement_gov_fee_id.recruitment_request_id = request.id

        self.recruitment_request_id = request.id
        self.state = 'done'
        self.message_post(body=_(
            'تم إنشاء سجل الموظف (%(emp)s) وطلب التوظيف %(req)s تلقائياً.'
        ) % {'emp': employee.display_name, 'req': request.name})
        request.message_post(body=_(
            'أُنشئ تلقائياً من طلب استقدام %s - الرسوم الحكومية مسدَّدة '
            'وسجل الموظف موجود مسبقاً.'
        ) % self.name)
