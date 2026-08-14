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
        if self.employee_id:
            self.current_project_id = self.employee_id.project_id

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
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.employee.platform.transfer.request'
                ) or _('جديد')
            if vals.get('employee_id') and not vals.get('current_project_id'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
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
            # حارس ضد تغيّر الوضع الفعلي منذ إنشاء الطلب (مثال: طلب آخر
            # نقل نفس الموظف لمنصة مختلفة وتم اعتماده أولاً) - بدل تنفيذ
            # نقل مبني على لقطة قديمة لم تعد صحيحة.
            if rec.current_project_id and rec.employee_id.project_id != rec.current_project_id:
                raise UserError(_(
                    'المنصة الحالية للموظف "%(employee)s" تغيّرت منذ إنشاء '
                    'هذا الطلب (أصبحت %(actual)s بدل %(expected)s) - ألغِ '
                    'هذا الطلب وأنشئ طلباً جديداً بالبيانات الصحيحة.'
                ) % {
                    'employee': rec.employee_id.display_name,
                    'actual': rec.employee_id.project_id.display_name or _('بلا منصة'),
                    'expected': rec.current_project_id.display_name,
                })
            rec.employee_id._open_platform_history(
                rec.new_project_id, note=rec.note, date_start=rec.transfer_date,
            )
        self.write({'state': 'done'})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'لا يمكن إعادة هذا الطلب لمسودة - النقل تم فعلاً. '
                    'أنشئ طلب نقل جديداً إن احتجت عكس النقل.'
                ))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'state': 'draft'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('لا يمكن إلغاء طلب نقل تم تنفيذه بالفعل.'))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'state': 'cancel'})
