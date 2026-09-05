# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetAccidentReport(models.Model):
    """بلاغ حادث مركبة - سجل مركزي يُبحث فيه، بدل كتابة رقم الحادث يدوياً
    في كل طلب تغيير مركبة بلا أي أثر مجمَّع.

    مبسَّط عمداً في هذه المرحلة (طلب صريح): يغطي ما هو مطلوب فعلياً الآن
    (رقم الحادث الرسمي، التاريخ، المركبة، المندوب، الوصف، تحديد
    المسؤولية، التقدير المبدئي، المرفقات عبر الدردشة) وقابل للتوسعة
    لاحقاً (مطالبات التأمين، أوامر الإصلاح، التسويات المالية) بلا إعادة
    بناء - كل التوسعات المتوقَّعة تُضاف كحقول/نماذج مرتبطة بهذا النموذج
    نفسه دون كسر أي شيء قائم.

    يُنشأ إما يدوياً من شاشته، أو تلقائياً عند اعتماد طلب تغيير مركبة
    نوعه "حادث" بلا بلاغ مرتبط (انظر fleet_vehicle_change_request.py:
    _ensure_accident_report)."""
    _name = 'fleet.accident.report'
    _description = 'بلاغ حادث مركبة'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'accident_date desc, id desc'

    name = fields.Char(
        string='رقم البلاغ', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    accident_number = fields.Char(
        string='رقم الحادث الرسمي', tracking=True,
        help='رقم الحادث الصادر من نجم/المرور - يُستخدَم للمطابقة مع '
             'الجهات الخارجية وشركة التأمين.',
    )
    accident_date = fields.Date(
        string='تاريخ الحادث', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة', required=True, tracking=True,
        ondelete='restrict',
        help='المركبة التي وقع عليها الحادث.',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='المندوب/السائق', tracking=True,
        ondelete='restrict',
        help='السائق وقت الحادث - يُقترَح تلقائياً من سائق المركبة الحالي.',
    )
    location = fields.Char(string='موقع الحادث')
    description = fields.Text(string='وصف الحادث')
    responsibility = fields.Selection(
        selection=[
            ('undetermined', 'غير محدد بعد'),
            ('employee', 'المندوب'),
            ('third_party', 'طرف آخر'),
            ('shared', 'مشتركة'),
        ],
        string='تحديد المسؤولية', default='undetermined', required=True,
        tracking=True,
        help='نتيجة تقرير تحديد المسؤولية - يُبنى عليها أي إجراء مالي لاحق.',
    )
    estimated_cost = fields.Monetary(
        string='التقدير المبدئي للأضرار', tracking=True,
        help='تقدير أولي فقط (وليس مطالبة فعلية) - المطالبة المالية على '
             'المندوب تُسجَّل عند لزومها كسجل "تحويل مركبة" في السداد '
             'البنكي فتظهر في كشف حسابه.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('confirmed', 'مؤكد'),
            ('closed', 'مغلق'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )
    change_request_ids = fields.One2many(
        'fleet.vehicle.change.request', 'accident_report_id',
        string='طلبات تغيير المركبة المرتبطة',
    )
    change_request_count = fields.Integer(
        string='عدد الطلبات المرتبطة', compute='_compute_change_request_count',
    )

    @api.depends('change_request_ids')
    def _compute_change_request_count(self):
        for rec in self:
            rec.change_request_count = len(rec.change_request_ids)

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        """يقترح السائق الحالي للمركبة كمندوب البلاغ - الاشتقاق نفسه
        يتم داخل fleet.vehicle._get_current_driver_employee() بـsudo،
        لأن الربط بين شريك السائق وسجل الموظف يمر عبر حقول "خاصة" على
        hr.employee (work_contact_id) لا يملكها مستخدم الأسطول بالضرورة."""
        if self.vehicle_id and not self.employee_id:
            self.employee_id = self.vehicle_id._get_current_driver_employee()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'fleet.accident.report'
                ) or _('جديد')
        return super().create(vals_list)

    def _check_group(self, *group_xmlids):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن تأكيد البلاغات في حالة "مسودة" فقط.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_fleet_supervisor',
                'recruitment_workflow.group_recruitment_workflow_fleet_manager',
            )
        self.write({'state': 'confirmed'})

    def action_close(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('يمكن إغلاق البلاغات المؤكدة فقط.'))
            if rec.responsibility == 'undetermined':
                raise UserError(_(
                    'لا يمكن إغلاق البلاغ قبل تحديد المسؤولية - هذه هي '
                    'النتيجة الأساسية التي يُبنى عليها أي إجراء مالي لاحق.'
                ))
            rec._check_group('recruitment_workflow.group_recruitment_workflow_fleet_manager')
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'draft':
                continue
            rec._check_group('recruitment_workflow.group_recruitment_workflow_fleet_manager')
        self.write({'state': 'draft'})

    def unlink(self):
        # بلاغ الحادث سجل تدقيق (يُبنى عليه طلب تغيير مركبة، وربما مطالبة
        # مالية على المندوب لاحقاً) - يُمنع حذفه بعد مغادرة "مسودة" بنفس
        # مبدأ بقية سجلات هذا الموديول. كذلك يُمنع حذف بلاغ مرتبط بطلب
        # تغيير مركبة قائم مهما كانت حالته - وإلا بقي الطلب يشير لبلاغ
        # محذوف (ondelete='restrict' على الطرف الآخر يمنع ذلك أصلاً، وهذا
        # الفحص يعطي رسالة مفهومة بدل خطأ قاعدة بيانات خام).
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف بلاغ الحادث "%s" بعد تأكيده - للحفاظ على '
                    'سجل تدقيق كامل. أعده لمسودة أولاً إن كان أُنشئ بالخطأ.'
                ) % rec.name)
            if rec.change_request_ids:
                raise UserError(_(
                    'لا يمكن حذف بلاغ الحادث "%s" - مرتبط بطلب/طلبات تغيير '
                    'مركبة. احذف الطلب المرتبط أولاً أو ألغِ ارتباطه.'
                ) % rec.name)
        return super().unlink()

    def action_view_change_requests(self):
        self.ensure_one()
        return {
            'name': _('طلبات تغيير المركبة - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.change.request',
            'view_mode': 'list,form',
            'domain': [('accident_report_id', '=', self.id)],
            'context': {'default_accident_report_id': self.id},
        }
