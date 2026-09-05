# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformTransferRequest(models.Model):
    """طلب نقل مندوب/موظف بين المنصات - يمر بخط سير موافقة بدل التنفيذ
    الفوري (كان سابقاً معالجاً مؤقتاً - hr.employee.platform.transfer.wizard
    - ينفّذ النقل بضغطة واحدة بلا أي أثر أو موافقة).

    الموافقة على مرحلتين:
    1. مسؤول المنصة الحالية للموظف تحديداً (project_id.user_id) - يوافق على
       تسريح الموظف من منصته. إن لم يكن للمنصة مسؤول معيّن، يُكتفى بصلاحية
       مدير العمليات كحل احتياطي (نفس فلسفة action_pm_approve في
       bank_settlement.advance).
    2. مدير العمليات - اعتماد نهائي، وينفّذ النقل الفعلي مباشرة عند نفس
       الضغطة (لا حاجة لخطوة تنفيذ منفصلة بعد الاعتماد النهائي - لا يوجد
       "تسليم فعلي" مادي يستوجب فاصلاً زمنياً كما في السداد البنكي).

    مبني على نفس مبدأ سير طلبات التوظيف (recruitment_request.py) - حالات
    ثابتة بالكود هنا (وليست نموذج مراحل قابل للتعديل مثل recruitment.stage،
    فالطلب أبسط بكثير ولا يحتاج هذه المرونة)، لكن بنفس الآليات المساعدة:
    - انتقال خطوة واحدة فقط للأمام عبر write() (يمنع القفز بالنقر المباشر
      على شريط الحالة القابل للنقر).
    - إشعار تلقائي (Activity) لصاحب القرار في كل مرحلة.
    - "إعادة لمسودة" ممنوعة مباشرة، وتمر حصراً عبر معالج يفرض تسجيل السبب
      (hr.employee.platform.transfer.reset.wizard) - بنفس مبدأ "إرجاع
      للتصحيح" (recruitment.return.wizard).
    """
    _name = 'hr.employee.platform.transfer.request'
    _description = 'طلب نقل موظف بين المنصات'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='الكود', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='الموظف', required=True, tracking=True,
        ondelete='restrict',
    )
    # لقطة من المنصة الحالية للموظف وقت إنشاء الطلب - وليست حقلاً مرتبطاً
    # حياً (related) بالمنصة الفعلية، حتى لا تتغير قيمتها ضمنياً لو نُقل
    # الموظف عبر طلب آخر بينما هذا الطلب لا يزال معلَّقاً (انظر أيضاً
    # التحقق من عدم تغيّرها فعلياً قبل التنفيذ في action_confirm_transfer).
    current_project_id = fields.Many2one(
        'project.project', string='المنصة الحالية', readonly=True,
    )
    new_project_id = fields.Many2one(
        'project.project', string='المنصة الجديدة', required=True, tracking=True,
    )
    transfer_date = fields.Date(
        string='تاريخ النقل', default=fields.Date.context_today,
        required=True, tracking=True,
    )
    note = fields.Char(string='سبب/ملاحظة النقل')
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_approval', 'بانتظار الموافقة'),
            ('pm_approved', 'وافق مسؤول المنصة الحالية'),
            ('done', 'تم النقل'),
            ('cancel', 'ملغى'),
        ],
        default='draft', tracking=True, copy=False,
    )

    # ترتيب الحالات الطبيعي - يُستخدم فقط لمنع القفز عدة خطوات دفعة واحدة
    # عبر write() مباشر (مثال: النقر على فقاعة متقدمة في شريط الحالة).
    # ليس نموذج مراحل قابلاً للتعديل (خلافاً لـ recruitment.stage) - الطلب
    # أبسط بكثير ولا يحتاج هذه المرونة.
    _STATE_SEQUENCE = ['draft', 'waiting_approval', 'pm_approved', 'done']

    @api.constrains('new_project_id', 'current_project_id')
    def _check_different_project(self):
        for rec in self:
            if rec.new_project_id and rec.current_project_id \
                    and rec.new_project_id.id == rec.current_project_id.id:
                raise UserError(_(
                    'الموظف يعمل بالفعل على هذه المنصة. اختر منصة مختلفة لإتمام النقل.'
                ))

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        # sudo(): project_id حقل "خاص" من منظور hr.employee.public، ومسؤول
        # المشروع/العمليات (المخوَّلان بإنشاء طلب النقل) لا يملكان بالضرورة
        # hr.group_hr_user - AccessError حقيقي عند اختيار الموظف من الواجهة
        # (اكتُشف بمحاكاة مباشرة بذاكرة تخزين مؤقت باردة، وليس عبر الاختبارات
        # التي كانت تُخفيه بسبب مشاركة الذاكرة المؤقتة مع بيئة الإداري).
        if self.employee_id:
            self.current_project_id = self.employee_id.sudo().project_id

    def _get_locked_fields_after_approval(self):
        """بيانات هوية الطلب (لمن، لأي منصة، متى) - لا يجوز تعديلها فور
        "إرسال للمراجعة" مباشرة، قبل أي موافقة فعلية - وإلا أصبحت موافقة
        مسؤول المنصة الحالية بلا معنى (يوافق على نقل، ثم يُغيَّر الموظف/
        المنصة المستهدفة بعد موافقته). note مستثناة عمداً - مجرد ملاحظة."""
        return ['employee_id', 'new_project_id', 'transfer_date']

    def write(self, vals):
        locked = self._get_locked_fields_after_approval()
        if any(f in vals for f in locked):
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(_(
                        'لا يمكن تعديل بيانات طلب النقل (الموظف/المنصة '
                        'الجديدة/التاريخ) بعد "إرسال للمراجعة" - أعد الطلب '
                        'لمسودة أولاً (زر "إعادة لمسودة") إن احتجت تصحيحها.'
                    ))
        if 'state' in vals and not self.env.context.get(
            'platform_transfer_skip_state_guard'
        ):
            new_state = vals['state']
            for rec in self:
                if new_state == rec.state or new_state == 'cancel':
                    # الإلغاء مسموح من أي حالة سابقة لـ"تم النقل" - الصلاحية
                    # الفعلية تُتحقق منها action_cancel نفسها قبل الوصول هنا.
                    continue
                if new_state == 'draft':
                    # الإرجاع لمسودة ممنوع مباشرة (نقر على شريط الحالة أو
                    # write() مباشر عبر RPC) - يجب أن يمر حصراً عبر معالج
                    # "إعادة لمسودة" الذي يفرض تسجيل سبب الإرجاع (انظر
                    # action_reset_draft أدناه).
                    raise UserError(_(
                        'لا يمكن إعادة الطلب لمسودة مباشرة. استخدم زر '
                        '"إعادة لمسودة" لتسجيل سبب الإرجاع.'
                    ))
                if rec.state not in self._STATE_SEQUENCE or new_state not in self._STATE_SEQUENCE:
                    continue
                old_index = self._STATE_SEQUENCE.index(rec.state)
                new_index = self._STATE_SEQUENCE.index(new_state)
                if new_index > old_index + 1:
                    raise UserError(_(
                        'لا يمكن القفز عدة مراحل دفعة واحدة (مثلاً بالنقر '
                        'على فقاعة متقدمة في شريط الحالة). استخدم الأزرار '
                        'الصريحة للانتقال خطوة بخطوة.'
                    ))
        res = super().write(vals)
        if 'state' in vals:
            for rec in self:
                rec._schedule_stage_activity()
        return res

    def unlink(self):
        # طلب نقل المنصة سجل تدقيق ومراجعة دائم (خصوصاً بعد كل القفل/منع
        # القفز/إشعارات الموافقة المبنية عليه) - يُمنع حذفه نهائياً بعد
        # مغادرة "مسودة" (حتى لمدير العمليات الذي يملك صلاحية الحذف)،
        # بنفس مبدأ recruitment_request.unlink(). "إلغاء" هو البديل
        # الوحيد لمن غادر "مسودة".
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف طلب النقل نهائياً بعد مغادرة "مسودة" - '
                    'للحفاظ على سجل تدقيق ومراجعة كامل. استخدم زر "إلغاء" '
                    'بدلاً من ذلك.'
                ))
        return super().unlink()

    def _get_first_group_user(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return group.all_user_ids[:1] if group else self.env['res.users']

    def _get_stage_responsible_user(self):
        """المستخدم الذي يجب تنبيهه بضرورة اتخاذ إجراء في الحالة الحالية -
        مسؤول المنصة الحالية تحديداً في "بانتظار الموافقة" إن كان معيّناً،
        وإلا أول عضو بمجموعة مدير العمليات (نفس فلسفة action_pm_approve)."""
        self.ensure_one()
        if self.state == 'waiting_approval':
            if self.current_project_id and self.current_project_id.user_id:
                return self.current_project_id.user_id
            return self._get_first_group_user(
                'recruitment_workflow.group_recruitment_workflow_operations'
            )
        if self.state == 'pm_approved':
            return self._get_first_group_user(
                'recruitment_workflow.group_recruitment_workflow_operations'
            )
        return self.env['res.users']

    def _schedule_stage_activity(self):
        """يُنهي أي نشاط (Activity) سابق متعلق بهذا الطلب - الحالة تغيّرت
        فالإجراء المطلوب سابقاً لم يعد ذا قيمة - ثم يجدول تنبيهاً جديداً
        لصاحب القرار في الحالة الجديدة (إن وُجد)، بدل تركه يكتشف وجود طلب
        بانتظاره بالصدفة."""
        self.ensure_one()
        self.activity_ids.action_feedback(feedback=_('تغيّرت حالة طلب النقل'))
        user = self._get_stage_responsible_user()
        if not user:
            return
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=_('مطلوب مراجعتك: طلب نقل موظف بين المنصات (%s)') % self.name,
            user_id=user.id,
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.employee.platform.transfer.request'
                ) or _('جديد')
            if vals.get('employee_id') and not vals.get('current_project_id'):
                # sudo(): project_id حقل "خاص" من منظور hr.employee.public -
                # يحدث هذا المسار عند create() مباشر بلا onchange (مثال:
                # إنشاء برمجي/RPC لا يمر بالواجهة) من مستخدم مسؤول مشروع/
                # عمليات لا يملك بالضرورة hr.group_hr_user.
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                vals['current_project_id'] = employee.project_id.id
        return super().create(vals_list)

    def _check_group(self, *group_xmlids):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن إرسال طلبات النقل في حالة "مسودة" فقط للمراجعة.'))
        self.write({'state': 'waiting_approval'})

    def action_pm_approve(self):
        """موافقة مسؤول المنصة الحالية للموظف تحديداً (current_project_id.
        user_id) - وليس أي عضو آخر في مجموعة مسؤولي المشاريع. إن لم تكن
        للمنصة الحالية مسؤول معيّن بعد، يُكتفى بالتحقق من صلاحية مدير
        العمليات كحل احتياطي."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise UserError(_('يمكن موافقة مسؤول المنصة الحالية في حالة "بانتظار الموافقة" فقط.'))
            current_pm = rec.current_project_id.user_id if rec.current_project_id else False
            if current_pm:
                if rec.env.user != current_pm:
                    raise UserError(_(
                        'هذه الموافقة تتطلب مسؤول المنصة الحالية للموظف '
                        'تحديداً (%s).'
                    ) % current_pm.name)
            else:
                rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'state': 'pm_approved'})

    def action_confirm_transfer(self):
        """اعتماد مدير العمليات النهائي - وينفّذ النقل الفعلي مباشرة عند
        نفس الضغطة (تحديث المنصة الحالية، تاريخ المنصات، العقد، والتوزيع
        التحليلي - عبر hr.employee._open_platform_history)."""
        for rec in self:
            if rec.state != 'pm_approved':
                raise UserError(_('يمكن اعتماد مدير العمليات بعد موافقة مسؤول المنصة الحالية فقط.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
            # sudo(): project_id حقل "خاص" من منظور hr.employee.public -
            # مدير العمليات (المخوَّل بهذا الاعتماد) لا يملك بالضرورة
            # hr.group_hr_user. القراءة داخلية بحتة (حارس تحقق فني) ولا
            # تعرض بيانات الموظف الشخصية للمستخدم مباشرة.
            employee = rec.employee_id.sudo()
            # حارس ضد تغيّر الوضع الفعلي منذ إنشاء الطلب (مثال: طلب آخر
            # نقل نفس الموظف لمنصة مختلفة وتم اعتماده أولاً) - بدل تنفيذ
            # نقل مبني على لقطة قديمة لم تعد صحيحة.
            if rec.current_project_id and employee.project_id != rec.current_project_id:
                raise UserError(_(
                    'المنصة الحالية للموظف "%(employee)s" تغيّرت منذ إنشاء '
                    'هذا الطلب (أصبحت %(actual)s بدل %(expected)s) - ألغِ '
                    'هذا الطلب وأنشئ طلباً جديداً بالبيانات الصحيحة.'
                ) % {
                    'employee': employee.display_name,
                    'actual': employee.project_id.display_name or _('بلا منصة'),
                    'expected': rec.current_project_id.display_name,
                })
            rec.employee_id._open_platform_history(
                rec.new_project_id, note=rec.note, date_start=rec.transfer_date,
            )
        self.write({'state': 'done'})

    def action_open_reset_wizard(self):
        """يفتح معالج "إعادة لمسودة" (يفرض تسجيل السبب) - الزر في الواجهة
        يستدعي هذه الدالة بدل action_reset_draft مباشرة."""
        self.ensure_one()
        return {
            'name': _('إعادة طلب النقل لمسودة'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.platform.transfer.reset.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_reset_draft(self, reason=False):
        """الإعادة الفعلية لمسودة - لا تُستدعى مباشرة من زر بالواجهة (انظر
        action_open_reset_wizard أعلاه)، بل من hr.employee.platform.
        transfer.reset.wizard فقط، الذي يفرض تمرير سبب الإرجاع."""
        if not reason:
            raise UserError(_('يجب توضيح سبب إعادة الطلب لمسودة.'))
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'لا يمكن إعادة هذا الطلب لمسودة - النقل تم فعلاً. '
                    'أنشئ طلب نقل جديداً إن احتجت عكس النقل.'
                ))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        for rec in self:
            rec.message_post(body=_(
                'تمت إعادة طلب النقل لمسودة للتصحيح.<br/>السبب: %s'
            ) % reason)
        self.with_context(platform_transfer_skip_state_guard=True).write({'state': 'draft'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('لا يمكن إلغاء طلب نقل تم تنفيذه بالفعل.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'state': 'cancel'})
