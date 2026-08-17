# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeeCost(models.Model):
    _name = 'hr.employee.cost'
    _description = 'تكلفة موظف مرتبطة بمشروع/منصة (تجديد إقامة، نقل، أخرى...)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'recruitment.workflow.analytic.mixin']
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='الوصف', compute='_compute_display_name', store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='المندوب/الموظف',
        required=True,
        tracking=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='المشروع / المنصة',
        required=True,
        tracking=True,
        help='المشروع الذي ستُحمَّل عليه هذه التكلفة تحليلياً. يُقترح '
             'تلقائياً من المنصة الحالية للموظف، ويمكن تغييره (مثال: تكلفة '
             'حصلت قبل النقل وتخص المنصة القديمة).',
    )
    cost_type_id = fields.Many2one(
        'hr.employee.cost.type',
        string='نوع التكلفة',
        required=True,
        tracking=True,
    )
    category = fields.Selection(
        related='cost_type_id.category',
        string='التصنيف',
        store=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='الجهة (المورّد)',
        help='الجهة الحكومية أو المورّد اللي ستُصدَر له فاتورة المورد '
             '(مثال: الجوازات، مؤسسة عامة، شركة خدمات النقل...). '
             'يُقترح تلقائياً من نوع التكلفة إن كان محدداً هناك.',
    )
    date = fields.Date(
        string='التاريخ', required=True, default=fields.Date.context_today, tracking=True,
    )
    amount = fields.Monetary(string='المبلغ', required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    description = fields.Text(string='تفاصيل')
    company_id = fields.Many2one(
        'res.company',
        string='الشركة',
        default=lambda self: self.env.company,
    )
    move_id = fields.Many2one(
        'account.move',
        string='فاتورة المورد',
        readonly=True,
        copy=False,
    )
    move_state = fields.Selection(
        related='move_id.state',
        string='حالة الفاتورة',
        readonly=True,
    )
    payment_state = fields.Selection(
        related='move_id.payment_state',
        string='حالة الدفع',
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('submitted', 'مرفوعة للمحاسبة'),
            ('cancelled', 'ملغاة'),
        ],
        string='الحالة',
        default='draft',
        tracking=True,
        copy=False,
        help='"مسودة": لسه بجانب التوظيف ولم تُرفع. "مرفوعة للمحاسبة": '
             'تم إنشاء فاتورة مورد وأصبحت مسؤولية فريق المحاسبة (مراجعة/'
             'اعتماد/دفع) من داخل تطبيق المحاسبة مباشرة.',
    )

    @api.depends('employee_id', 'cost_type_id', 'amount')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (
                rec.cost_type_id.name or _('تكلفة'), rec.employee_id.name or '',
            )

    @api.constrains('amount')
    def _check_amount_positive(self):
        """يمنع مبلغاً سالباً أو صفرياً - كان بلا أي تحقق سابقاً، يمكن
        رفع تكلفة بمبلغ سالب فعلياً كفاتورة مورد حقيقية (ثغرة مكتشفة
        بمراجعة شاملة)."""
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('المبلغ يجب أن يكون أكبر من صفر.'))

    def unlink(self):
        # تكاليف الموظفين سجل تدقيق ومراجعة دائم مرتبط بفواتير موردين
        # حقيقية - يُمنع حذفها نهائياً بعد مغادرة "مسودة" (حتى لممن يملك
        # صلاحية الحذف)، بنفس مبدأ recruitment_request.unlink(). "إلغاء"
        # هو البديل الوحيد لمن غادر "مسودة".
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف هذه التكلفة نهائياً بعد مغادرة "مسودة" - '
                    'للحفاظ على سجل تدقيق ومراجعة كامل. استخدم "إلغاء" '
                    'بدلاً من ذلك.'
                ))
        return super().unlink()

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.project_id:
            self.project_id = self.employee_id.project_id

    @api.onchange('cost_type_id')
    def _onchange_cost_type_id(self):
        if self.cost_type_id and self.cost_type_id.partner_id and not self.partner_id:
            self.partner_id = self.cost_type_id.partner_id

    def _get_analytic_distribution(self):
        self.ensure_one()
        if not self.analytic_account_id:
            return {}
        return {str(self.analytic_account_id.id): 100.0}

    def action_submit_to_accounting(self):
        """يرفع التكلفة للمحاسبة: ينشئ فاتورة مورد (Vendor Bill) في حالة
        مسودة داخل تطبيق المحاسبة، موزّعة تحليلياً على المشروع/المنصة.

        من هذه اللحظة، المراجعة والاعتماد والدفع كلها مسؤولية فريق المحاسبة
        من داخل شاشاتهم الطبيعية (فواتير الموردين ← الدفعات)، ولا حاجة
        للرجوع لموديول التوظيف لإتمامها.
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن رفع التكاليف في حالة "مسودة" فقط.'))
            if not rec.analytic_account_id:
                raise UserError(_(
                    'لا يوجد حساب تحليلي على المشروع "%s". تأكد من إعداد '
                    'الحساب التحليلي للمشروع قبل الرفع للمحاسبة.'
                ) % rec.project_id.display_name)
            if not rec.partner_id:
                raise UserError(_(
                    'حدد الجهة/المورّد الذي ستُصدَر له الفاتورة قبل الرفع للمحاسبة.'
                ))

            distribution = rec._get_analytic_distribution()
            line_fields = self.env['account.move.line']._fields
            line_vals = {
                'name': rec.description or rec.display_name,
                'quantity': 1.0,
                'price_unit': rec.amount,
            }
            if rec.cost_type_id.expense_account_id and 'account_id' in line_fields:
                line_vals['account_id'] = rec.cost_type_id.expense_account_id.id
            if 'analytic_distribution' in line_fields and distribution:
                line_vals['analytic_distribution'] = distribution
            elif 'analytic_account_id' in line_fields and rec.analytic_account_id:
                line_vals['analytic_account_id'] = rec.analytic_account_id.id

            move_vals = {
                'move_type': 'in_invoice',
                'partner_id': rec.partner_id.id,
                'invoice_date': rec.date,
                'ref': rec.display_name,
                'company_id': rec.company_id.id,
                'invoice_line_ids': [(0, 0, line_vals)],
            }
            if rec.cost_type_id.journal_id:
                move_vals['journal_id'] = rec.cost_type_id.journal_id.id

            move = self.env['account.move'].sudo().create(move_vals)
            rec.write({'move_id': move.id, 'state': 'submitted'})
            rec.message_post(body=_(
                'تم رفع التكلفة كفاتورة مورد %(move)s (مسودة) لفريق المحاسبة '
                'لمراجعتها واعتمادها ودفعها، موزّعة تحليلياً على مشروع %(project)s.'
            ) % {'move': move.display_name, 'project': rec.project_id.display_name})
            rec._schedule_accounting_review_activity()

    def _schedule_accounting_review_activity(self):
        """يجدول نشاطاً (Activity) لأول مستخدم في مجموعة "المحاسب"، ويرسل
        له أيضاً رسالة مباشرة في صندوق الدردشة (Discuss/الجرس) - كانت
        هذه التكلفة تُرفع لفريق المحاسبة بلا أي إشعار فعلي سابقاً، فيجب
        عليهم تفقّد قائمة فواتير الموردين يدوياً لاكتشاف وجود فاتورة
        جديدة بانتظارهم. القناتان معاً بطلب صريح - النشاط وحده لا يظهر
        في صندوق الدردشة (شاشة "الأنشطة" منفصلة عنه)."""
        self.ensure_one()
        group = self.env.ref(
            'recruitment_workflow.group_recruitment_workflow_accountant',
            raise_if_not_found=False,
        )
        if not group or not group.all_user_ids:
            return
        user = group.all_user_ids[0]
        self.activity_schedule(
            act_type_xmlid='mail.mail_activity_data_todo',
            summary=_('مطلوب منك: مراجعة واعتماد فاتورة مورد - %s') % self.display_name,
            note=_('التكلفة: %s - المبلغ: %s') % (self.display_name, self.amount),
            user_id=user.id,
        )
        if user.partner_id:
            self.message_post(
                body=_('مطلوب منك: مراجعة واعتماد فاتورة مورد - %s.') % self.display_name,
                partner_ids=user.partner_id.ids,
            )

    def action_view_move(self):
        self.ensure_one()
        # حماية من جهة الخادم: عضو مجموعة "مستخدم" الأساسية يملك قراءة فقط
        # على هذا النموذج، لكن دون هذا التحقق يستطيع فتح فاتورة المورد
        # الفعلية في المحاسبة عبر هذا الزر رغم عدم امتلاكه صلاحية مالية.
        if not self.env.user.has_group('recruitment_workflow.group_recruitment_workflow_operations'):
            raise UserError(_('ليست لديك الصلاحية للاطّلاع على فاتورة المورد.'))
        if not self.move_id:
            raise UserError(_('لا يوجد فاتورة مورد مرتبطة بعد.'))
        return {
            'name': _('فاتورة المورد'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(_(
                    'فاتورة المورد مرحّلة بالفعل في المحاسبة. ألغِها أو '
                    'اعكسها من داخل تطبيق المحاسبة أولاً.'
                ))
            if rec.move_id and rec.move_id.state == 'draft':
                rec.move_id.sudo().button_cancel()
            rec.state = 'cancelled'
            rec.message_post(body=_('تم إلغاء التكلفة.'))

    def action_reset_to_draft(self):
        for rec in self:
            if rec.move_id:
                raise UserError(_(
                    'لا يمكن إعادة هذه التكلفة لمسودة لوجود فاتورة مورد '
                    'مرتبطة بها. أنشئ سطراً جديداً بدلاً من ذلك.'
                ))
            rec.state = 'draft'
