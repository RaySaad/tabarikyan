# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetServiceRequest(models.Model):
    """طلب صيانة يرفعه الفرع إلى الأسطول.

    المركبة ملك الأسطول وهو من يُدخلها الورشة، لكن من يرى العطل أولاً
    هو الفرع الذي تعمل عنده. بلا هذا النموذج كان الطلب يمر بالهاتف:
    لا تاريخ، ولا أثر، ولا وسيلة لقياس زمن الاستجابة.

    الفرع يُنشئ ويقرأ فقط - القبول والرفض والتنفيذ من الأسطول، فحالة
    الطلب لا تُزوَّر من طرف واحد.
    """
    _name = 'fleet.service.request'
    _description = 'طلب صيانة من الفرع'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='الطلب', compute='_compute_name', store=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة', required=True, tracking=True,
        ondelete='restrict',
    )
    # شركة الطالب: الفرع الذي المركبة لديه يوم الطلب - لا شركة المركبة.
    company_id = fields.Many2one(
        'res.company', string='الفرع الطالب', required=True, index=True,
        compute='_compute_company_id', store=True, readonly=False,
        precompute=True,
    )
    fleet_company_id = fields.Many2one(
        'res.company', string='الأسطول',
        related='vehicle_id.company_id', store=True, readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='المندوب', ondelete='restrict',
        help='سائق المركبة وقت الطلب - يُقترح من العقد.',
    )
    request_type = fields.Selection(
        selection=[
            ('periodic', 'صيانة دورية'),
            ('breakdown', 'عطل'),
            ('accident', 'ضرر حادث'),
            ('tyres', 'إطارات'),
            ('other', 'أخرى'),
        ],
        string='نوع الطلب', required=True, default='breakdown', tracking=True,
    )
    urgency = fields.Selection(
        selection=[
            ('normal', 'عادي'),
            ('urgent', 'عاجل - المركبة متوقفة'),
        ],
        string='الاستعجال', default='normal', required=True, tracking=True,
    )
    date_request = fields.Date(
        string='تاريخ الطلب', required=True, default=fields.Date.context_today)
    odometer = fields.Float(string='قراءة العدّاد')
    description = fields.Text(string='وصف العطل', required=True)

    state = fields.Selection(
        selection=[
            ('new', 'مُقدَّم'),
            ('accepted', 'مقبول'),
            ('done', 'نُفِّذ'),
            ('refused', 'مرفوض'),
        ],
        string='الحالة', default='new', required=True, tracking=True, copy=False,
    )
    fleet_note = fields.Text(string='رد الأسطول', tracking=True)
    service_log_id = fields.Many2one(
        'fleet.vehicle.log.services', string='سجل الورشة', readonly=True,
        copy=False, help='يُربط عند تنفيذ الصيانة لتُعرف تكلفتها.',
    )

    @api.depends('vehicle_id', 'request_type', 'date_request')
    def _compute_name(self):
        labels = dict(self._fields['request_type'].selection)
        for rec in self:
            rec.name = '%s - %s' % (
                rec.vehicle_id.display_name or '',
                labels.get(rec.request_type, ''))

    @api.depends('vehicle_id')
    def _compute_company_id(self):
        for rec in self:
            branch = rec.vehicle_id.rental_branch_id
            # بلا عقد سارٍ: المركبة لدى الأسطول نفسه.
            rec.company_id = (
                branch or rec.vehicle_id.company_id or self.env.company)

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        contract = self.vehicle_id.rental_contract_id
        if contract.employee_id:
            self.employee_id = contract.employee_id
        if self.vehicle_id.odometer and not self.odometer:
            self.odometer = self.vehicle_id.odometer

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Vehicle = self.env['fleet.vehicle']
        for vals in vals_list:
            # تُملأ قبل الإنشاء لا بعده: مشرف الفرع يملك الإنشاء بلا
            # تعديل، فكتابة أي حقل بعد super تُسقط إنشاءه هو نفسه
            # بـAccessError (أسقطها الاختبار قبل أن تصل إليه).
            if not vals.get('employee_id') and vals.get('vehicle_id'):
                contract = Vehicle.browse(
                    vals['vehicle_id']).sudo().rental_contract_id
                if contract.employee_id:
                    vals['employee_id'] = contract.employee_id.id
        requests = super().create(vals_list)
        for request in requests:
            request._notify_fleet()
        return requests

    def _notify_fleet(self):
        """نشاط لمسؤول المركبة في الأسطول.

        بـsudo: مُنشئ الطلب مشرف فرع لا يملك الكتابة على الطلب ولا
        صلاحيات الأسطول، والتنبيه يجب ألا يتعطّل بسببه."""
        self.ensure_one()
        user = self.vehicle_id.manager_id
        if not user:
            group = self.env.ref(
                'recruitment_workflow.group_recruitment_workflow_fleet_manager',
                raise_if_not_found=False)
            # all_user_ids لا users: أودو 19 غيّرت الاسم، وتشمل من
            # نال المجموعة بالتضمين لا بالمنح المباشر وحده.
            user = group.all_user_ids[:1] if group else self.env['res.users']
        if not user:
            return
        self.sudo().activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_('طلب صيانة: %s') % self.vehicle_id.display_name,
            note=self.description or '',
            user_id=user.id,
        )

    # -- إجراءات الأسطول ------------------------------------------------
    def action_accept(self):
        for rec in self:
            if rec.state != 'new':
                raise UserError(_('لا يُقبل إلا طلب مُقدَّم.'))
        self.write({'state': 'accepted'})

    def action_refuse(self):
        for rec in self:
            if rec.state in ('done',):
                raise UserError(_('الطلب نُفِّذ فعلاً - لا يُرفض بعدها.'))
            if not rec.fleet_note:
                raise UserError(_(
                    'اكتب سبب الرفض في "رد الأسطول" - الفرع يقرأه.'))
        self.write({'state': 'refused'})

    def action_done(self):
        """تنفيذ الصيانة: يفتح معالج تسجيل الخدمة على المركبة نفسها."""
        self.ensure_one()
        if self.state == 'refused':
            raise UserError(_('طلب مرفوض لا يُنفَّذ - أعد فتحه بقبوله أولاً.'))
        return {
            'name': _('تسجيل تنفيذ الصيانة'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.service.request.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _close_with_service(self, date, amount, note=False):
        """يُسجّل خدمة على المركبة ويقفل الطلب بها."""
        self.ensure_one()
        log = self.env['fleet.vehicle.log.services'].sudo().create({
            'vehicle_id': self.vehicle_id.id,
            'date': date,
            'amount': amount,
            'description': note or self.description or self.name,
        })
        self.write({'state': 'done', 'service_log_id': log.id})
        self.message_post(body=_(
            'نُفِّذت الصيانة في %(date)s بتكلفة %(amount)s.'
        ) % {'date': date, 'amount': amount})
        return log


class FleetServiceRequestCloseWizard(models.TransientModel):
    _name = 'fleet.service.request.close.wizard'
    _description = 'إقفال طلب صيانة'

    request_id = fields.Many2one(
        'fleet.service.request', string='الطلب', required=True, readonly=True)
    vehicle_id = fields.Many2one(related='request_id.vehicle_id', readonly=True)
    date = fields.Date(
        string='تاريخ التنفيذ', required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string='التكلفة')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    note = fields.Char(string='ما تم عمله')

    def action_confirm(self):
        self.ensure_one()
        self.request_id._close_with_service(self.date, self.amount, self.note)
        return {'type': 'ir.actions.act_window_close'}
