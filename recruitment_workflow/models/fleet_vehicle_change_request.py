# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .fleet_vehicle_change_config import VEHICLE_CHANGE_TYPES


class FleetVehicleChangeRequest(models.Model):
    """طلب تغيير مركبة مندوب (حادث / عطل / لوحة) - يمر بخط سير موافقة
    كامل ثم ينفّذ التغيير فعلياً عند الاعتماد النهائي، بدل تعديل سائق
    المركبة يدوياً بلا أثر ولا موافقة.

    خط السير (مبني على نفس قالب hr.employee.platform.transfer.request
    المُختبر: منع القفز بين المراحل، قفل البيانات بعد الإرسال، إعادة
    لمسودة بسبب إجباري، إشعار تلقائي لصاحب القرار في كل مرحلة، منع
    الحذف بعد المسودة):

        مسودة
          -> بانتظار مشرف الحركة
          -> بانتظار مدير الصيانة   (لطلبات "حادث"/"عطل" فقط)
          -> بانتظار مدير العمليات
          -> بانتظار اعتماد مدير الحركة
          -> تم التنفيذ

    مرحلة مدير الصيانة تُتخطى تلقائياً في طلبات "لوحة" (لا علاقة لها
    بالصيانة) - بنفس مبدأ تخطي مراحل نقل الكفالة في طلبات الاستقدام
    (recruitment_request._IMPORT_SKIPPED_STAGE_CODES): تسلسل المراحل
    يُحسَب لكل سجل على حدة (_get_state_sequence)، فيبقى حارس "لا قفز بين
    المراحل" صحيحاً في الحالتين بلا استثناءات مكتوبة يدوياً.

    "المركبة الجديدة" اختيارية عمداً (طلب صريح): تُترك فارغة في حالة
    سحب المركبة من المندوب بلا بديل (إيقاف مندوب، أو حادث بلا مركبة
    بديلة متاحة فوراً)."""
    _name = 'fleet.vehicle.change.request'
    _description = 'طلب تغيير مركبة'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='الكود', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )

    # -- بيانات الموظف ---------------------------------------------------
    employee_id = fields.Many2one(
        'hr.employee', string='الموظف/المندوب', required=True, tracking=True,
        ondelete='restrict',
    )
    # groups='' صراحة على الحقول الثلاثة المشتقة من ملف الموظف: بدونها
    # ترث تلقائياً قيد hr.group_hr_user المفروض على الحقول الأصلية في نواة
    # hr (حماية خصوصية معيارية) - فيفشل فتح الشاشة بالكامل (AccessError)
    # لأي مستخدم أسطول/حركة لا يملك تلك الصلاحية، رغم أن هذه البيانات
    # ضرورية له هنا. نفس الثغرة الحقيقية التي اكتُشفت سابقاً في
    # bank_settlement (residency_number) وعولجت بنفس الأسلوب.
    residency_number = fields.Char(
        string='رقم الإقامة', related='employee_id.identification_id',
        readonly=True, groups='',
    )
    birthday = fields.Date(
        string='تاريخ الميلاد', related='employee_id.birthday',
        readonly=True, groups='',
    )
    absher_mobile = fields.Char(
        string='رقم جوال أبشر', related='employee_id.absher_mobile',
        readonly=True, groups='',
    )
    project_id = fields.Many2one(
        'project.project', string='المنصة', related='employee_id.project_id',
        readonly=True, groups='',
    )

    # -- المركبة الحالية --------------------------------------------------
    current_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة الحالية', required=True,
        tracking=True, ondelete='restrict',
        help='تُقترَح تلقائياً من المركبة المخصَّصة حالياً للمندوب.',
    )
    current_plate = fields.Char(
        string='رقم اللوحة (الحالية)',
        related='current_vehicle_id.license_plate', readonly=True,
    )
    current_vin = fields.Char(
        string='الرقم التسلسلي (الحالية)',
        related='current_vehicle_id.vin_sn', readonly=True,
    )
    current_model_id = fields.Many2one(
        'fleet.vehicle.model', string='نوع المركبة (الحالية)',
        related='current_vehicle_id.model_id', readonly=True,
    )
    current_vehicle_company_id = fields.Many2one(
        'res.company', string='مالكية المركبة (الحالية)',
        related='current_vehicle_id.company_id', readonly=True,
    )

    # -- المركبة الجديدة (اختيارية) ---------------------------------------
    new_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة الجديدة', tracking=True,
        ondelete='restrict',
        help='اتركها فارغة إن كان المطلوب سحب المركبة من المندوب بلا بديل.',
    )
    new_plate = fields.Char(
        string='رقم اللوحة (الجديدة)',
        related='new_vehicle_id.license_plate', readonly=True,
    )
    new_vin = fields.Char(
        string='الرقم التسلسلي (الجديدة)',
        related='new_vehicle_id.vin_sn', readonly=True,
    )
    new_model_id = fields.Many2one(
        'fleet.vehicle.model', string='نوع المركبة (الجديدة)',
        related='new_vehicle_id.model_id', readonly=True,
    )
    new_vehicle_company_id = fields.Many2one(
        'res.company', string='مالكية المركبة (الجديدة)',
        related='new_vehicle_id.company_id', readonly=True,
    )

    # -- تفاصيل الطلب -----------------------------------------------------
    request_type = fields.Selection(
        selection=VEHICLE_CHANGE_TYPES, string='نوع الطلب',
        required=True, default='breakdown', tracking=True,
        help='يحدد المرفقات المطلوبة، ومرحلة موافقة مدير الصيانة '
             '(لا تظهر في طلبات "لوحة")، ومصير المركبة القديمة المقترَح.',
    )
    reason_id = fields.Many2one(
        'fleet.vehicle.change.reason', string='سبب التبديل', tracking=True,
        help='قائمة مفلترة تلقائياً حسب نوع الطلب - تُدار من '
             'سير عمل التوظيف ← الإعدادات ← أسباب تبديل المركبات.',
    )
    accident_report_id = fields.Many2one(
        'fleet.accident.report', string='بلاغ الحادث', tracking=True,
        ondelete='restrict',
        help='يُختار من البلاغات المسجَّلة، أو يُنشأ تلقائياً عند الاعتماد '
             'النهائي إن لم يُحدَّد.',
    )
    accident_number = fields.Char(
        string='رقم الحادث الرسمي',
        related='accident_report_id.accident_number', readonly=True,
    )
    old_vehicle_target_state = fields.Selection(
        selection=[
            ('under_repair', 'تحت الإصلاح'),
            ('out_of_service', 'خارج الخدمة'),
            ('available', 'متاحة'),
        ],
        string='مصير المركبة القديمة', required=True, default='under_repair',
        tracking=True,
        help='الحالة التي تُضبَط عليها المركبة القديمة بعد سحبها من '
             'المندوب. "تحت الإصلاح"/"خارج الخدمة" تُخرجها تلقائياً من '
             'المركبات المتاحة في طلبات التوظيف.',
    )
    note = fields.Text(string='ملاحظات')

    # -- تواريخ تلقائية ----------------------------------------------------
    request_date = fields.Date(
        string='تاريخ إنشاء الطلب', default=fields.Date.context_today,
        readonly=True, copy=False,
    )
    approval_date = fields.Date(
        string='تاريخ الموافقة', readonly=True, copy=False,
        help='يُسجَّل تلقائياً عند اعتماد مدير العمليات.',
    )
    authorization_date = fields.Date(
        string='تاريخ التفويض', readonly=True, copy=False,
        help='يُسجَّل تلقائياً لحظة التنفيذ الفعلي (اعتماد مدير الحركة).',
    )

    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )

    attachment_line_ids = fields.One2many(
        'fleet.vehicle.change.attachment', 'request_id', string='المرفقات',
    )
    maintenance_log_id = fields.Many2one(
        'fleet.vehicle.log.services', string='سجل الصيانة', readonly=True,
        copy=False,
        help='يُنشأ تلقائياً على المركبة القديمة عند تنفيذ طلب نوعه "عطل".',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_supervisor', 'بانتظار مشرف الحركة'),
            ('waiting_maintenance', 'بانتظار مدير الصيانة'),
            ('waiting_ops', 'بانتظار مدير العمليات'),
            ('waiting_manager', 'بانتظار اعتماد مدير الحركة'),
            ('done', 'تم التنفيذ'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )
    rejection_reason = fields.Text(string='سبب الإرجاع/الإلغاء', copy=False)

    # ------------------------------------------------------------------
    # تسلسل المراحل (مع تخطي مرحلة الصيانة في طلبات "لوحة")
    # ------------------------------------------------------------------
    def _get_state_sequence(self):
        """تسلسل المراحل الفعلي لهذا السجل تحديداً - مرحلة مدير الصيانة
        غير موجودة أصلاً في تسلسل طلبات "لوحة"، فلا حاجة لأي استثناء
        مكتوب يدوياً في حارس "لا قفز بين المراحل" ولا في أزرار الواجهة."""
        self.ensure_one()
        states = ['draft', 'waiting_supervisor']
        if self.request_type in ('accident', 'breakdown'):
            states.append('waiting_maintenance')
        states += ['waiting_ops', 'waiting_manager', 'done']
        return states

    def _next_state(self):
        self.ensure_one()
        sequence = self._get_state_sequence()
        if self.state not in sequence:
            return False
        index = sequence.index(self.state)
        return sequence[index + 1] if index + 1 < len(sequence) else False

    # ------------------------------------------------------------------
    # قيود التحقق
    # ------------------------------------------------------------------
    @api.constrains('current_vehicle_id', 'new_vehicle_id')
    def _check_different_vehicles(self):
        for rec in self:
            if rec.new_vehicle_id and rec.new_vehicle_id == rec.current_vehicle_id:
                raise UserError(_(
                    'المركبة الجديدة هي نفسها المركبة الحالية - اختر مركبة '
                    'مختلفة، أو اتركها فارغة إن كان المطلوب سحب المركبة بلا بديل.'
                ))

    @api.constrains('new_vehicle_id', 'employee_id')
    def _check_new_vehicle_company(self):
        """المركبة الجديدة يجب أن تكون من نفس فرع/شركة الموظف - نفس
        الحماية الموجودة في طلبات التوظيف (_check_vehicle_company)، وإلا
        أمكن تخصيص مركبة فرع لموظف فرع آخر فتختل ملكية الأصول والتكاليف
        بين الفروع."""
        for rec in self:
            if not (rec.new_vehicle_id and rec.employee_id):
                continue
            employee_company = rec.employee_id.sudo().company_id
            vehicle_company = rec.new_vehicle_id.sudo().company_id
            if employee_company and vehicle_company and employee_company != vehicle_company:
                raise UserError(_(
                    'المركبة الجديدة "%(vehicle)s" تتبع الفرع "%(vcompany)s" '
                    'بينما الموظف يتبع الفرع "%(ecompany)s" - اختر مركبة من '
                    'نفس فرع الموظف، أو انقل المركبة للفرع أولاً.'
                ) % {
                    'vehicle': rec.new_vehicle_id.display_name,
                    'vcompany': vehicle_company.display_name,
                    'ecompany': employee_company.display_name,
                })

    # ------------------------------------------------------------------
    # onchange / التعبئة التلقائية
    # ------------------------------------------------------------------
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """يجلب المركبة المخصَّصة حالياً للمندوب - sudo() داخل الدالة
        المساعدة نفسها (hr.employee._get_current_vehicle) لأن الربط يمر
        عبر شريك الموظف الشخصي، وهو حقل "خاص" لا يملكه مستخدم الحركة
        بالضرورة."""
        if not self.employee_id:
            return
        vehicle = self.employee_id._get_current_vehicle()
        if vehicle:
            self.current_vehicle_id = vehicle
        if self.employee_id.sudo().company_id:
            self.company_id = self.employee_id.sudo().company_id

    @api.onchange('request_type')
    def _onchange_request_type(self):
        """يضبط مصير المركبة القديمة المقترَح حسب النوع، ويفرغ السبب/بلاغ
        الحادث إن لم يعودا مناسبين للنوع الجديد - بدل ترك قيم لا تنتمي
        للنوع المختار (سبب "عطل" على طلب "لوحة" مثلاً)."""
        if self.request_type in ('accident', 'breakdown'):
            self.old_vehicle_target_state = 'under_repair'
        else:
            self.old_vehicle_target_state = 'available'
        if self.request_type != 'accident':
            self.accident_report_id = False
        if self.reason_id and self.reason_id.request_type not in ('all', self.request_type):
            self.reason_id = False

    # ------------------------------------------------------------------
    # المرفقات
    # ------------------------------------------------------------------
    def _get_expected_attachment_types(self):
        self.ensure_one()
        return self.env['fleet.vehicle.change.attachment.type'].search([
            ('request_type', 'in', ['all', self.request_type]),
        ])

    def _sync_attachment_lines(self):
        """يبني/يحدّث أسطر المرفقات المطلوبة حسب نوع الطلب الحالي - تُحذف
        الأسطر التي لم تعد مطلوبة بعد تغيير النوع *فقط إن كانت فارغة*
        (سطر رُفع فيه ملف فعلاً يبقى دائماً، حتى لا يفقد المستخدم مستنداً
        رفعه بالفعل بمجرد تصحيح نوع الطلب)."""
        AttachmentLine = self.env['fleet.vehicle.change.attachment']
        for rec in self:
            expected_types = rec._get_expected_attachment_types()
            existing = rec.attachment_line_ids
            obsolete = existing.filtered(
                lambda l: l.attachment_type_id not in expected_types and not l.file
            )
            if obsolete:
                obsolete.unlink()
            existing_types = (existing - obsolete).mapped('attachment_type_id')
            missing = expected_types - existing_types
            for attachment_type in missing:
                AttachmentLine.create({
                    'request_id': rec.id,
                    'attachment_type_id': attachment_type.id,
                    'sequence': attachment_type.sequence,
                })

    def _check_required_attachments(self):
        """يمنع إرسال الطلب للمراجعة قبل رفع كل المرفقات الإجبارية لنوعه
        (طلب صريح: "إلزام إرفاق..." لكل من الحادث والعطل) - الفحص هنا من
        جهة الخادم، وليس مجرد إخفاء زر في الواجهة."""
        for rec in self:
            missing = rec.attachment_line_ids.filtered(
                lambda l: l.required and not l.file
            )
            if missing:
                raise UserError(_(
                    'لا يمكن إرسال الطلب قبل رفع المرفقات الإجبارية التالية:\n- %s'
                ) % '\n- '.join(missing.mapped('attachment_type_id.name')))

    # ------------------------------------------------------------------
    # create / write / unlink
    # ------------------------------------------------------------------
    def _get_locked_fields_after_submit(self):
        """بيانات هوية الطلب (لمن، أي مركبة، لأي سبب) - لا يجوز تعديلها
        بعد "إرسال للمراجعة"، وإلا أصبحت كل موافقة سابقة بلا معنى (يوافق
        مشرف الحركة على تغيير مركبة معيّنة، ثم تُبدَّل المركبة بعد
        موافقته). الملاحظات ومصير المركبة القديمة مستثنيان عمداً: الأول
        نص إرشادي، والثاني قرار فني يخص قسم الحركة/الصيانة نفسه ويُحدَّد
        غالباً أثناء المراجعة لا قبلها."""
        return [
            'employee_id', 'current_vehicle_id', 'new_vehicle_id',
            'request_type', 'accident_report_id',
        ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'fleet.vehicle.change.request'
                ) or _('جديد')
            if vals.get('employee_id') and not vals.get('company_id'):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                if employee.company_id:
                    vals['company_id'] = employee.company_id.id
        records = super().create(vals_list)
        records._sync_attachment_lines()
        return records

    def write(self, vals):
        locked = self._get_locked_fields_after_submit()
        # vehicle_change_internal_write: يُتجاوز القفل عمداً لعمليات نظامية
        # محدَّدة يقوم بها الكود نفسه أثناء التنفيذ (ربط بلاغ الحادث
        # المُنشأ تلقائياً) - وليست تعديلاً يدوياً من مستخدم على طلب
        # مُعتمَد. بدونه كان الاعتماد النهائي لطلب "حادث" يفشل بالكامل
        # برسالة "لا يمكن تعديل بيانات الطلب الأساسية" - ثغرة حقيقية
        # اكتشفها الاختبار الآلي قبل الوصول للمستخدم. نفس مبدأ
        # bank_settlement_skip_approval_lock في السداد البنكي.
        if any(f in vals for f in locked) and not self.env.context.get(
            'vehicle_change_internal_write'
        ):
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(_(
                        'لا يمكن تعديل بيانات الطلب الأساسية (الموظف/'
                        'المركبات/نوع الطلب) بعد إرساله للمراجعة - استخدم '
                        '"إعادة لمسودة" لتصحيحها.'
                    ))
        if 'state' in vals and not self.env.context.get(
            'vehicle_change_skip_state_guard'
        ):
            new_state = vals['state']
            for rec in self:
                if new_state in (rec.state, 'cancel'):
                    continue
                if new_state == 'draft':
                    raise UserError(_(
                        'لا يمكن إعادة الطلب لمسودة مباشرة. استخدم زر '
                        '"إعادة لمسودة" لتسجيل سبب الإرجاع.'
                    ))
                sequence = rec._get_state_sequence()
                if rec.state not in sequence or new_state not in sequence:
                    continue
                if sequence.index(new_state) > sequence.index(rec.state) + 1:
                    raise UserError(_(
                        'لا يمكن القفز عدة مراحل دفعة واحدة (مثلاً بالنقر '
                        'على فقاعة متقدمة في شريط الحالة). استخدم الأزرار '
                        'الصريحة للانتقال خطوة بخطوة.'
                    ))
        res = super().write(vals)
        if 'request_type' in vals:
            self._sync_attachment_lines()
        if 'state' in vals:
            for rec in self:
                rec._schedule_stage_activity()
        return res

    def unlink(self):
        # طلب تغيير المركبة سجل تدقيق (تُبنى عليه موافقات، وتغيير فعلي
        # لتخصيص أصل، وربما سجل صيانة وبلاغ حادث) - يُمنع حذفه بعد مغادرة
        # "مسودة" بنفس مبدأ بقية سجلات الموديول. "إلغاء" هو البديل.
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف طلب تغيير المركبة نهائياً بعد مغادرة '
                    '"مسودة" - للحفاظ على سجل تدقيق كامل. استخدم زر '
                    '"إلغاء" بدلاً من ذلك.'
                ))
        return super().unlink()

    # ------------------------------------------------------------------
    # الإشعارات
    # ------------------------------------------------------------------
    def _get_first_group_user(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return group.all_user_ids[:1] if group else self.env['res.users']

    def _get_stage_responsible_user(self):
        self.ensure_one()
        group_by_state = {
            'waiting_supervisor': 'recruitment_workflow.group_recruitment_workflow_fleet_supervisor',
            'waiting_maintenance': 'recruitment_workflow.group_recruitment_workflow_maintenance_manager',
            'waiting_ops': 'recruitment_workflow.group_recruitment_workflow_operations',
            'waiting_manager': 'recruitment_workflow.group_recruitment_workflow_fleet_manager',
        }
        group_xmlid = group_by_state.get(self.state)
        if not group_xmlid:
            return self.env['res.users']
        return self._get_first_group_user(group_xmlid)

    def _schedule_stage_activity(self):
        """يُنهي أي نشاط سابق (الحالة تغيّرت فالإجراء المطلوب سابقاً لم
        يعد ذا قيمة) ثم يجدول تنبيهاً جديداً لصاحب القرار في الحالة
        الجديدة - وعند الوصول لحالة نهائية يُبلَّغ مُنشئ الطلب نفسه
        (طلب صريح: إشعار المشرف عند الموافقة أو الرفض)."""
        self.ensure_one()
        self.activity_ids.action_feedback(feedback=_('تغيّرت حالة الطلب'))
        if self.state in ('done', 'cancel'):
            creator_partner = self.create_uid.partner_id
            if creator_partner:
                label = _('تم تنفيذ الطلب') if self.state == 'done' else _('أُلغي الطلب')
                self.message_post(
                    body=_('%(label)s: %(name)s') % {'label': label, 'name': self.name},
                    partner_ids=creator_partner.ids,
                )
            return
        user = self._get_stage_responsible_user()
        if not user:
            return
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=_('مطلوب مراجعتك: طلب تغيير مركبة (%s)') % self.name,
            user_id=user.id,
        )
        if user.partner_id:
            self.message_post(
                body=_('مطلوب إجراؤك على طلب تغيير المركبة %s.') % self.name,
                partner_ids=user.partner_id.ids,
            )

    # ------------------------------------------------------------------
    # انتقالات الحالة
    # ------------------------------------------------------------------
    def _check_group(self, *group_xmlids):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    def _advance(self, expected_state, *group_xmlids):
        """خطوة موافقة واحدة: تتحقق من الحالة الحالية ومن صلاحية المستخدم،
        ثم تنتقل للحالة التالية *في تسلسل هذا السجل تحديداً* (فتتخطى
        مرحلة الصيانة تلقائياً في طلبات "لوحة")."""
        for rec in self:
            if rec.state != expected_state:
                raise UserError(_(
                    'هذا الإجراء متاح في حالة "%s" فقط.'
                ) % dict(rec._fields['state'].selection).get(expected_state, expected_state))
            if group_xmlids:
                rec._check_group(*group_xmlids)
        for rec in self:
            next_state = rec._next_state()
            if not next_state:
                raise UserError(_('لا توجد مرحلة تالية لهذا الطلب.'))
            rec.write({'state': next_state})

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن إرسال الطلبات في حالة "مسودة" فقط للمراجعة.'))
            if not rec.current_vehicle_id:
                raise UserError(_('يجب تحديد المركبة الحالية قبل إرسال الطلب.'))
        self._check_required_attachments()
        self._advance('draft')

    def action_supervisor_approve(self):
        self._advance(
            'waiting_supervisor',
            'recruitment_workflow.group_recruitment_workflow_fleet_supervisor',
            'recruitment_workflow.group_recruitment_workflow_fleet_manager',
        )

    def action_maintenance_approve(self):
        self._advance(
            'waiting_maintenance',
            'recruitment_workflow.group_recruitment_workflow_maintenance_manager',
        )

    def action_ops_approve(self):
        for rec in self:
            if rec.state != 'waiting_ops':
                raise UserError(_('هذا الإجراء متاح في حالة "بانتظار مدير العمليات" فقط.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'approval_date': fields.Date.context_today(self)})
        self._advance('waiting_ops')

    def action_manager_confirm(self):
        """الاعتماد النهائي من مدير الحركة - وينفّذ التغيير الفعلي مباشرة
        عند نفس الضغطة (بنفس مبدأ action_confirm_transfer في طلب نقل
        المنصة: لا حاجة لخطوة تنفيذ منفصلة بعد الاعتماد النهائي)."""
        for rec in self:
            if rec.state != 'waiting_manager':
                raise UserError(_('هذا الإجراء متاح في حالة "بانتظار اعتماد مدير الحركة" فقط.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_fleet_manager')
        for rec in self:
            rec._execute_vehicle_change()
        self._advance('waiting_manager')

    def action_open_reset_wizard(self):
        self.ensure_one()
        return {
            'name': _('إعادة الطلب لمسودة'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.change.reset.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_reset_draft(self, reason=False):
        """الإعادة الفعلية لمسودة - لا تُستدعى من زر مباشرة، بل عبر
        fleet.vehicle.change.reset.wizard الذي يفرض تسجيل السبب."""
        if not reason:
            raise UserError(_('يجب توضيح سبب إعادة الطلب لمسودة.'))
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'لا يمكن إعادة هذا الطلب لمسودة - التغيير نُفِّذ فعلاً. '
                    'أنشئ طلباً جديداً إن احتجت عكس التغيير.'
                ))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_fleet_manager',
                'recruitment_workflow.group_recruitment_workflow_operations',
            )
        for rec in self:
            rec.message_post(body=_(
                'تمت إعادة الطلب لمسودة للتصحيح.<br/>السبب: %s'
            ) % reason)
        self.with_context(vehicle_change_skip_state_guard=True).write({
            'state': 'draft', 'rejection_reason': reason,
        })

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('لا يمكن إلغاء طلب نُفِّذ بالفعل.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_fleet_manager',
                'recruitment_workflow.group_recruitment_workflow_operations',
            )
        self.write({'state': 'cancel'})

    # ------------------------------------------------------------------
    # التنفيذ الفعلي
    # ------------------------------------------------------------------
    def _check_execution_guards(self):
        """حراس ضد تغيّر الوضع الفعلي منذ إنشاء الطلب - بدل تنفيذ تغيير
        مبني على لقطة قديمة لم تعد صحيحة (نفس مبدأ الحارس في
        hr.employee.platform.transfer.request.action_confirm_transfer)."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee._get_personal_partner()
        old_vehicle = self.current_vehicle_id.sudo()
        if partner and old_vehicle.driver_id and old_vehicle.driver_id != partner:
            raise UserError(_(
                'المركبة الحالية "%(vehicle)s" لم تعد مخصَّصة للموظف '
                '"%(employee)s" (سائقها الآن: %(driver)s) - ألغِ هذا الطلب '
                'وأنشئ طلباً جديداً بالبيانات الصحيحة.'
            ) % {
                'vehicle': old_vehicle.display_name,
                'employee': employee.display_name,
                'driver': old_vehicle.driver_id.display_name,
            })
        new_vehicle = self.new_vehicle_id.sudo()
        if not new_vehicle:
            return
        if new_vehicle.recruitment_state != 'available':
            raise UserError(_(
                'المركبة الجديدة "%(vehicle)s" لم تعد متاحة (حالتها الآن: '
                '%(state)s) - اختر مركبة أخرى متاحة.'
            ) % {
                'vehicle': new_vehicle.display_name,
                'state': dict(
                    new_vehicle._fields['recruitment_state'].selection
                ).get(new_vehicle.recruitment_state, new_vehicle.recruitment_state),
            })
        if new_vehicle.driver_id and partner and new_vehicle.driver_id != partner:
            raise UserError(_(
                'المركبة الجديدة "%s" مخصَّصة لسائق آخر بالفعل.'
            ) % new_vehicle.display_name)

    def _ensure_accident_report(self):
        """يضمن وجود بلاغ حادث مرتبط بطلبات نوعها "حادث" - يُنشأ تلقائياً
        (مسودة، ببيانات الطلب) إن لم يكن المستخدم قد اختار بلاغاً قائماً،
        بدل ضياع الحادث بلا سجل مركزي."""
        self.ensure_one()
        if self.request_type != 'accident' or self.accident_report_id:
            return self.accident_report_id
        report = self.env['fleet.accident.report'].sudo().create({
            'accident_date': self.request_date or fields.Date.context_today(self),
            'vehicle_id': self.current_vehicle_id.id,
            'employee_id': self.employee_id.id,
            'description': self.note or '',
            'company_id': self.company_id.id,
        })
        self.with_context(vehicle_change_internal_write=True).accident_report_id = report.id
        self.message_post(body=_(
            'أُنشئ بلاغ حادث تلقائياً: %s - يُرجى استكمال بياناته '
            '(رقم الحادث الرسمي وتحديد المسؤولية).'
        ) % report.name)
        return report

    def _create_maintenance_log(self):
        """يسجّل العطل في سجل صيانة المركبة القياسي بأودو (fleet.vehicle.
        log.services) - بدل سجل صيانة مخصَّص موازٍ لا يراه قسم الأسطول في
        شاشاته المعتادة."""
        self.ensure_one()
        if self.request_type != 'breakdown' or self.maintenance_log_id:
            return self.maintenance_log_id
        vals = {
            'vehicle_id': self.current_vehicle_id.id,
            'date': fields.Date.context_today(self),
            'description': _('عطل - %s') % self.name,
            'notes': self.note or (self.reason_id.name if self.reason_id else ''),
            'company_id': self.company_id.id,
        }
        service_type = self.env.ref(
            'recruitment_workflow.fleet_service_type_breakdown',
            raise_if_not_found=False,
        )
        if service_type:
            vals['service_type_id'] = service_type.id
        log = self.env['fleet.vehicle.log.services'].sudo().create(vals)
        self.maintenance_log_id = log.id
        return log

    def _execute_vehicle_change(self):
        """التنفيذ الفعلي: سحب المركبة القديمة من المندوب وضبط مصيرها،
        وتخصيص الجديدة له (إن وُجدت). تعديل driver_id يجعل أودو نفسها
        تسجّل سجل الإسقاط التاريخي (fleet.vehicle.assignation.log) لكل
        مركبة تلقائياً - فلا حاجة لسجل تاريخي مخصَّص موازٍ."""
        self.ensure_one()
        self._check_execution_guards()
        employee = self.employee_id.sudo()
        partner = employee._get_personal_partner()
        old_vehicle = self.current_vehicle_id.sudo()
        new_vehicle = self.new_vehicle_id.sudo()

        # sudo() على كل كتابات المركبات: قاعدة أودو الأساسية "Fleet
        # vehicle: Multi Company" تقيّد الكتابة على fleet.vehicle بشركات
        # المستخدم - ومدير الحركة المعتمِد قد لا يكون عضواً في فرع المركبة
        # نفسه، فتُرفَض الكتابة بصمت رغم أن صلاحية الإجراء محكومة أصلاً
        # عبر _check_group قبل الوصول هنا (نفس الثغرة الحقيقية المشروحة
        # في fleet_vehicle._open_branch_history).
        old_vehicle.write({
            'driver_id': False,
            'future_driver_id': False,
            'recruitment_state': self.old_vehicle_target_state,
        })
        old_vehicle.message_post(body=_(
            'سُحبت المركبة من المندوب "%(employee)s" بموجب طلب تغيير المركبة '
            '%(request)s، وأصبحت حالتها: %(state)s.'
        ) % {
            'employee': employee.display_name,
            'request': self.name,
            'state': dict(
                self._fields['old_vehicle_target_state'].selection
            ).get(self.old_vehicle_target_state, self.old_vehicle_target_state),
        })

        if new_vehicle:
            new_vals = {'recruitment_state': 'assigned', 'future_driver_id': False}
            if partner:
                new_vals['driver_id'] = partner.id
            new_vehicle.write(new_vals)
            new_vehicle.message_post(body=_(
                'خُصِّصت المركبة للمندوب "%(employee)s" بموجب طلب تغيير المركبة %(request)s.'
            ) % {'employee': employee.display_name, 'request': self.name})
            self.authorization_date = fields.Date.context_today(self)

        self._ensure_accident_report()
        self._create_maintenance_log()

        self.message_post(body=_(
            'نُفِّذ التغيير: سُحبت %(old)s%(new)s.'
        ) % {
            'old': old_vehicle.display_name,
            'new': (
                _(' وخُصِّصت %s') % new_vehicle.display_name
                if new_vehicle else _(' بلا مركبة بديلة')
            ),
        })

    # ------------------------------------------------------------------
    # أزرار العرض
    # ------------------------------------------------------------------
    def action_view_accident_report(self):
        self.ensure_one()
        if not self.accident_report_id:
            raise UserError(_('لا يوجد بلاغ حادث مرتبط بهذا الطلب.'))
        return {
            'name': _('بلاغ الحادث'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.accident.report',
            'res_id': self.accident_report_id.id,
            'view_mode': 'form',
        }

    def action_view_maintenance_log(self):
        self.ensure_one()
        if not self.maintenance_log_id:
            raise UserError(_('لا يوجد سجل صيانة مرتبط بهذا الطلب.'))
        return {
            'name': _('سجل الصيانة'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.log.services',
            'res_id': self.maintenance_log_id.id,
            'view_mode': 'form',
        }


class FleetVehicleChangeAttachment(models.Model):
    """مرفق فعلي مرفوع على طلب تغيير مركبة - نفس بنية recruitment.request.
    attachment المُختبرة (نوع المرفق + ملف + علم "إجباري" مشتق من النوع)."""
    _name = 'fleet.vehicle.change.attachment'
    _description = 'مرفق طلب تغيير المركبة'
    _order = 'sequence, id'

    request_id = fields.Many2one(
        'fleet.vehicle.change.request', string='الطلب', required=True,
        ondelete='cascade', index=True,
    )
    attachment_type_id = fields.Many2one(
        'fleet.vehicle.change.attachment.type', string='نوع المرفق',
        required=True, ondelete='restrict',
    )
    # store=False صراحة - نفس سبب recruitment.request.attachment.name
    # بالضبط (حقل مصدره مترجَم؛ تخزينه يسبب تعارض نوع عمود jsonb/varchar
    # عند أي تعديل لاحق على translate). انظر الشرح الكامل هناك.
    name = fields.Char(
        string='المرفق', related='attachment_type_id.name',
        store=False, readonly=True,
    )
    sequence = fields.Integer(string='الترتيب', default=10)
    required = fields.Boolean(
        string='إجباري', related='attachment_type_id.required',
        store=True, readonly=True,
    )
    file = fields.Binary(string='الملف', attachment=True)
    file_name = fields.Char(string='اسم الملف')
    is_uploaded = fields.Boolean(string='تم الرفع', compute='_compute_is_uploaded')

    @api.depends('file')
    def _compute_is_uploaded(self):
        for rec in self:
            rec.is_uploaded = bool(rec.file)
