# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeeExitRequest(models.Model):
    """طلب إنهاء خدمة موظف (استقالة / فصل / انتهاء عقد) - يمر بخط سير
    موافقة، ثم ينفّذ عند الاعتماد النهائي كل الآثار المترتبة على الخروج
    دفعة واحدة بدل تركها لذاكرة الموظفين.

    قبل هذه الميزة كانت أرشفة الموظف لا تفعل شيئاً غيرها إطلاقاً: تبقى
    سيارته مخصَّصة له (فلا يستطيع مندوب جديد أخذها)، وتبقى فترة منصته
    مفتوحة بلا تاريخ نهاية، ويستمر جدول "الدفعة المقدمة" بترحيل مصروف
    شهري على منصة موظف غادر أصلاً - ثغرات تشغيلية ومحاسبية حقيقية.

    ما يُنفَّذ تلقائياً عند الاعتماد النهائي (_execute_exit):
    1. طلب تغيير مركبة "سحب بلا بديل" - فلا تعود المركبة "متاحة" إلا
       بعد أن يستلمها قسم الحركة فعلياً ويسجّل عدادها وحالتها.
    2. إغلاق فترة المنصة الحالية بتاريخ آخر يوم عمل.
    3. تسجيل سبب/تاريخ المغادرة القياسيين، إنهاء العقد، وأرشفة الموظف.
    4. (يُوسِّعه bank_settlement) إيقاف ما تبقّى من جداول الدفعات المقدمة.

    الموانع (سلف غير مسددة، مركبة لم تُستلم...) تُعرَض كتحذير ظاهر ولا
    تمنع الاعتماد - قرار صريح: مندوب غادر فعلاً يجب أن يُغلَق ملفه، وتبقى
    مستحقاته تُعالَج من تصفيته النهائية."""
    _name = 'hr.employee.exit.request'
    _description = 'طلب إنهاء خدمة'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='الرقم', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='الموظف', required=True, tracking=True,
        ondelete='restrict', index=True,
    )
    exit_type = fields.Selection(
        selection=[
            ('resignation', 'استقالة'),
            ('termination', 'فصل'),
            ('contract_end', 'انتهاء عقد'),
        ],
        string='نوع الخروج', required=True, default='resignation', tracking=True,
    )
    departure_reason_id = fields.Many2one(
        'hr.departure.reason', string='سبب المغادرة (أودو)',
        ondelete='restrict',
        help='يُملأ تلقائياً حسب نوع الخروج - يُسجَّل على ملف الموظف '
             'ليظهر في تقارير الموارد البشرية القياسية.',
    )
    request_date = fields.Date(
        string='تاريخ الطلب', default=fields.Date.context_today, readonly=True,
    )
    last_working_date = fields.Date(
        string='آخر يوم عمل', required=True, tracking=True,
        default=fields.Date.context_today,
        help='تُغلق عنده فترة المنصة، فلا تُحمَّل على المندوب أي تكلفة بعده.',
    )
    reason = fields.Text(string='السبب/الملاحظات')
    warning_id = fields.Many2one(
        'hr.employee.warning', string='الإنذار النهائي', readonly=True,
        copy=False, ondelete='restrict',
    )
    project_id = fields.Many2one(
        'project.project', string='المنصة', related='employee_id.project_id',
        readonly=True, groups='',
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )

    vehicle_change_request_id = fields.Many2one(
        'fleet.vehicle.change.request', string='طلب سحب المركبة', readonly=True,
        copy=False,
        help='يُنشأ تلقائياً عند التنفيذ - المركبة لا تعود "متاحة" إلا '
             'بعد استلامها فعلياً من قسم الحركة.',
    )
    current_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة الحالية',
        compute='_compute_current_vehicle_id',
    )
    pending_items = fields.Text(
        string='معلقات قبل الخروج', compute='_compute_pending_items',
        help='تُعرَض للمراجعة فقط ولا تمنع الاعتماد - المستحقات تُعالَج '
             'من التصفية النهائية.',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_pm', 'بانتظار مسؤول المنصة'),
            ('waiting_hr', 'بانتظار الموارد البشرية'),
            ('done', 'نُفِّذ'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )
    _STATE_SEQUENCE = ['draft', 'waiting_pm', 'waiting_hr', 'done']

    _DEPARTURE_REASON_BY_TYPE = {
        'resignation': 'hr.departure_resigned',
        'termination': 'hr.departure_fired',
        # سبب مستقل - ربطه بـ"فصل" كان يشوّه تقارير الموارد البشرية
        # القياسية (انتهاء عقد ليس فصلاً).
        'contract_end': 'recruitment_workflow.departure_contract_end',
    }

    # ------------------------------------------------------------------
    def _compute_current_vehicle_id(self):
        for rec in self:
            rec.current_vehicle_id = (
                rec.employee_id._get_current_vehicle() if rec.employee_id
                else self.env['fleet.vehicle']
            )

    def _get_exit_pending_items(self):
        """قائمة المعلقات المعروضة على الطلب - يوسّعها bank_settlement
        بالسلف والرسوم وجداول الدفعات المقدمة (اتجاه الاعتماد: السداد
        البنكي يعرف التوظيف، لا العكس)."""
        self.ensure_one()
        items = []
        vehicle = self.current_vehicle_id
        if vehicle:
            items.append(_('مركبة ما زالت مخصَّصة له: %s') % vehicle.display_name)
        return items

    @api.depends('employee_id')
    def _compute_pending_items(self):
        for rec in self:
            items = rec._get_exit_pending_items() if rec.employee_id else []
            rec.pending_items = '\n'.join('• %s' % item for item in items)

    @api.onchange('exit_type')
    def _onchange_exit_type(self):
        reason_xmlid = self._DEPARTURE_REASON_BY_TYPE.get(self.exit_type)
        if reason_xmlid:
            reason = self.env.ref(reason_xmlid, raise_if_not_found=False)
            if reason:
                self.departure_reason_id = reason.id

    @api.constrains('employee_id', 'state')
    def _check_single_open_request(self):
        """طلبان مفتوحان لنفس الموظف يعنيان تنفيذ الخروج مرتين (وأرشفة
        وسحب مركبة مكرَّرين) - يُمنع صراحة."""
        for rec in self:
            if rec.state in ('done', 'cancel'):
                continue
            duplicate = self.search_count([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'not in', ('done', 'cancel')),
            ])
            if duplicate:
                raise UserError(_(
                    'يوجد طلب إنهاء خدمة مفتوح بالفعل للموظف "%s" - أكمله '
                    'أو ألغِه بدل فتح طلب ثانٍ.'
                ) % rec.employee_id.display_name)

    # ------------------------------------------------------------------
    def _get_locked_fields_after_submit(self):
        return ['employee_id', 'exit_type', 'last_working_date']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.employee.exit.request'
                ) or _('جديد')
            if vals.get('exit_type') and not vals.get('departure_reason_id'):
                reason = self.env.ref(
                    self._DEPARTURE_REASON_BY_TYPE.get(vals['exit_type'], ''),
                    raise_if_not_found=False,
                )
                if reason:
                    vals['departure_reason_id'] = reason.id
            if vals.get('employee_id') and not vals.get('company_id'):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                if employee.company_id:
                    vals['company_id'] = employee.company_id.id
        return super().create(vals_list)

    def write(self, vals):
        locked = self._get_locked_fields_after_submit()
        if any(f in vals for f in locked):
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(_(
                        'لا يمكن تعديل بيانات الطلب الأساسية (الموظف/نوع '
                        'الخروج/آخر يوم عمل) بعد إرساله للمراجعة.'
                    ))
        if 'state' in vals and not self.env.context.get('exit_request_skip_state_guard'):
            new_state = vals['state']
            for rec in self:
                if new_state in (rec.state, 'cancel', 'draft'):
                    continue
                if rec.state not in self._STATE_SEQUENCE or new_state not in self._STATE_SEQUENCE:
                    continue
                if self._STATE_SEQUENCE.index(new_state) > self._STATE_SEQUENCE.index(rec.state) + 1:
                    raise UserError(_(
                        'لا يمكن القفز عدة مراحل دفعة واحدة - استخدم '
                        'الأزرار الصريحة للانتقال خطوة بخطوة.'
                    ))
        res = super().write(vals)
        if 'state' in vals:
            for rec in self:
                rec._schedule_stage_activity()
        return res

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف طلب إنهاء الخدمة بعد مغادرة "مسودة" - '
                    'للحفاظ على سجل تدقيق كامل. استخدم "إلغاء" بدلاً من ذلك.'
                ))
        return super().unlink()

    # ------------------------------------------------------------------
    def _get_first_group_user(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return group.all_user_ids[:1] if group else self.env['res.users']

    def _get_stage_responsible_user(self):
        self.ensure_one()
        if self.state == 'waiting_pm':
            project = self.employee_id.sudo().project_id
            if project and project.user_id:
                return project.user_id
            return self._get_first_group_user(
                'recruitment_workflow.group_recruitment_workflow_operations')
        if self.state == 'waiting_hr':
            return self._get_first_group_user(
                'recruitment_workflow.group_recruitment_workflow_hr')
        return self.env['res.users']

    def _schedule_stage_activity(self):
        self.ensure_one()
        self.activity_ids.action_feedback(feedback=_('تغيّرت حالة الطلب'))
        user = self._get_stage_responsible_user()
        if not user:
            return
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=_('مطلوب مراجعتك: طلب إنهاء خدمة (%s)') % self.name,
            user_id=user.id,
        )

    def _check_group(self, *group_xmlids):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    # -- انتقالات الحالة ---------------------------------------------------
    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن إرسال الطلبات في حالة "مسودة" فقط.'))
        self.write({'state': 'waiting_pm'})

    def action_pm_approve(self):
        for rec in self:
            if rec.state != 'waiting_pm':
                raise UserError(_('هذا الإجراء متاح في حالة "بانتظار مسؤول المنصة" فقط.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_project_manager',
                'recruitment_workflow.group_recruitment_workflow_operations',
            )
        self.write({'state': 'waiting_hr'})

    def action_confirm_exit(self):
        """الاعتماد النهائي - وينفّذ كل آثار الخروج مباشرة."""
        for rec in self:
            if rec.state != 'waiting_hr':
                raise UserError(_('هذا الإجراء متاح في حالة "بانتظار الموارد البشرية" فقط.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_hr',
                'recruitment_workflow.group_recruitment_workflow_operations',
            )
        for rec in self:
            rec._execute_exit()
        self.write({'state': 'done'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'لا يمكن إلغاء طلب نُفِّذ بالفعل - أعِد تفعيل الموظف '
                    'يدوياً إن كان الخروج قد سُجّل بالخطأ.'
                ))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_hr',
                'recruitment_workflow.group_recruitment_workflow_operations',
            )
        self.write({'state': 'cancel'})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('لا يمكن إعادة طلب نُفِّذ بالفعل لمسودة.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.with_context(exit_request_skip_state_guard=True).write({'state': 'draft'})

    # -- التنفيذ ------------------------------------------------------------
    def _execute_exit(self):
        """كل آثار الخروج دفعة واحدة - يوسّعه bank_settlement بإيقاف
        جداول الدفعات المقدمة."""
        self.ensure_one()
        self._create_vehicle_withdrawal_request()
        self._close_employee_platform()
        self._apply_departure_on_employee()
        self.message_post(body=_('نُفِّذ إنهاء الخدمة: %s') % self.name)

    def _create_vehicle_withdrawal_request(self):
        """ينشئ طلب تغيير مركبة نوعه "خروج مندوب" (سحب بلا بديل) بدل
        تحرير المركبة مباشرة - فتُوثَّق حالة المركبة وعدادها لحظة
        استلامها فعلياً، ولا تعود "متاحة" لمندوب جديد قبل ذلك (قرار
        صريح)."""
        self.ensure_one()
        vehicle = self.current_vehicle_id
        if not vehicle or self.vehicle_change_request_id:
            return self.vehicle_change_request_id
        request = self.env['fleet.vehicle.change.request'].sudo().create({
            'employee_id': self.employee_id.id,
            'request_type': 'exit',
            'current_vehicle_id': vehicle.id,
            'old_vehicle_target_state': 'available',
            'company_id': self.company_id.id,
            'note': _('سحب المركبة بموجب إنهاء خدمة %s') % self.name,
        })
        self.vehicle_change_request_id = request.id
        # يُرسَل للمراجعة فوراً بدل تركه مسودة صامتة: لولا ذلك لما وصل
        # قسم الحركة أي إشعار (الإشعارات مبنية على تغيّر الحالة)، فتبقى
        # المركبة "مخصَّصة" لموظف غادر إلى أن يكتشفها أحد بالصدفة.
        request.sudo().action_submit_review()
        self.message_post(body=_(
            'أُنشئ طلب سحب المركبة (%(request)s) وأُرسل لمشرف الحركة - '
            'المركبة "%(vehicle)s" لن تعود متاحة إلا بعد استلامها فعلياً.'
        ) % {'request': request.name, 'vehicle': vehicle.display_name})
        return request

    def _close_employee_platform(self):
        """يغلق فترة المنصة المفتوحة بتاريخ آخر يوم عمل - بدونها تبقى
        الفترة مفتوحة للأبد فيُحمَّل على المنصة تكاليف موظف غادر."""
        self.ensure_one()
        self.employee_id._close_platform_history(self.last_working_date)

    def _apply_departure_on_employee(self):
        """يسجّل بيانات المغادرة القياسية بأودو، ينهي العقد الحالي،
        ويؤرشف الموظف - بنفس ما يفعله معالج المغادرة القياسي، لكن ضمن
        سير موافقة موثَّق بدل ضغطة واحدة بلا أثر."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        employee.write({
            'departure_reason_id': self.departure_reason_id.id or False,
            'departure_date': self.last_working_date,
            'departure_description': self.reason or '',
        })
        # إنهاء العقد الحالي (hr.version في أودو 19) - نتجاهل بهدوء إن
        # لم يكن للموظف عقد فعّال، فليس شرطاً لإتمام الخروج.
        version = employee.version_id if 'version_id' in employee._fields else False
        if version and 'contract_date_end' in version._fields and version.contract_date_start:
            version.sudo().write({'contract_date_end': self.last_working_date})
        if employee.active:
            employee.with_context(no_wizard=True).action_archive()

    # -- أزرار العرض --------------------------------------------------------
    def action_view_vehicle_request(self):
        self.ensure_one()
        if not self.vehicle_change_request_id:
            raise UserError(_('لا يوجد طلب سحب مركبة مرتبط.'))
        return {
            'name': _('طلب سحب المركبة'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.change.request',
            'res_id': self.vehicle_change_request_id.id,
            'view_mode': 'form',
        }
