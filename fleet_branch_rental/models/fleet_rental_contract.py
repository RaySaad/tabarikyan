# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FleetRentalContract(models.Model):
    """عقد تأجير مركبة من شركة الأسطول إلى فرع التشغيل.

    يصدر بموافقة الأسطول نفسها على طلب السيارة - خطوة واحدة لا
    دورتا اعتماد: الضغط على "تفويض السيارة" يخصّص المركبة ويُصدر
    العقد سارياً في آنٍ واحد.

    وهو سجل **الاستخدام** لا الملكية: المركبة تبقى في دفاتر شركة
    الأسطول، والعقد يقول أي فرع يستعملها ومن متى إلى متى وبأي أجرة -
    وعليه يُحتسب التحميل الشهري.
    """
    _name = 'fleet.rental.contract'
    _description = 'عقد تأجير مركبة لفرع'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(
        string='رقم العقد', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    fleet_company_id = fields.Many2one(
        'res.company', string='المؤجِّر (الأسطول)', required=True, readonly=True,
        default=lambda self: self.env['res.company']._get_fleet_owner_company(),
    )
    company_id = fields.Many2one(
        'res.company', string='المستأجر (الفرع)', required=True, tracking=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة', required=True, tracking=True,
        ondelete='restrict',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='المندوب', tracking=True, ondelete='restrict',
        help='السائق الذي سُلِّمت له المركبة - للتوثيق وتحديد المسؤولية.',
    )
    recruitment_request_id = fields.Many2one(
        'recruitment.request', string='طلب السيارة', readonly=True, copy=False,
    )
    date_start = fields.Date(
        string='تاريخ التسليم', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    date_end = fields.Date(
        string='تاريخ الإرجاع', tracking=True, copy=False,
        help='يُضبط تلقائياً عند سحب المركبة أو الحادث أو خروج المندوب - '
             'وتتوقف الأجرة من يومه.',
    )
    monthly_rate = fields.Monetary(
        string='الأجرة الشهرية', required=True, tracking=True,
        help='تُقترح من بطاقة المركبة وتبقى قابلة للتعديل قبل الإصدار.',
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    state = fields.Selection(
        selection=[
            ('active', 'ساري'),
            ('ended', 'منتهٍ'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='active', required=True, tracking=True, copy=False,
    )
    end_reason = fields.Char(string='سبب الإنهاء', readonly=True, copy=False)
    note = fields.Text(string='ملاحظات')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_(
                    'تاريخ الإرجاع قبل تاريخ التسليم في العقد %s.') % rec.name)

    @api.constrains('vehicle_id', 'date_start', 'date_end', 'state')
    def _check_no_overlap(self):
        """مركبة واحدة لا تكون لدى فرعين في اليوم نفسه - وإلا حُمِّلت
        أجرتها مرتين."""
        for rec in self.filtered(lambda c: c.state == 'active'):
            domain = [
                ('id', '!=', rec.id),
                ('vehicle_id', '=', rec.vehicle_id.id),
                ('state', '=', 'active'),
                ('date_start', '<=', rec.date_end or rec.date_start),
            ]
            for other in self.sudo().search(domain):
                if not other.date_end or other.date_end > rec.date_start:
                    raise ValidationError(_(
                        'المركبة "%(vehicle)s" مرتبطة بعقد ساري آخر '
                        '(%(contract)s) يتقاطع مع هذه الفترة.'
                    ) % {'vehicle': rec.vehicle_id.display_name,
                         'contract': other.name})

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id and not self.monthly_rate:
            self.monthly_rate = self.vehicle_id.rental_monthly_rate

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'fleet.rental.contract') or _('جديد')
            if not vals.get('fleet_company_id'):
                vals['fleet_company_id'] = self.env['res.company'] \
                    ._get_fleet_owner_company().id
        return super().create(vals_list)

    def unlink(self):
        charged = self.env['fleet.branch.rental.charge.line'].sudo().search([
            ('contract_id', 'in', self.ids),
        ], limit=1)
        if charged:
            raise UserError(_(
                'لا يمكن حذف عقد حُمِّلت أجرته (%s) - ألغِه بدل حذفه.'
            ) % charged.contract_id.name)
        return super().unlink()

    # ------------------------------------------------------------------
    def action_end(self, reason=False, date_end=None):
        """إنهاء العقد: الأجرة تتوقف من هذا التاريخ."""
        date_end = date_end or fields.Date.context_today(self)
        for rec in self:
            if rec.state != 'active':
                continue
            rec.write({
                'date_end': date_end,
                'end_reason': reason or _('إرجاع المركبة'),
                'state': 'ended',
            })
            rec.message_post(body=_('انتهى العقد في %(date)s - %(reason)s')
                             % {'date': date_end, 'reason': rec.end_reason})
        return True

    def action_cancel(self):
        for rec in self:
            charged = self.env['fleet.branch.rental.charge.line'].sudo().search([
                ('contract_id', '=', rec.id),
                ('charge_id.state', '=', 'posted'),
            ], limit=1)
            if charged:
                raise UserError(_(
                    'العقد %(name)s حُمِّلت أجرته في %(charge)s - أنهِه بدل '
                    'إلغائه، أو ألغِ التحميل أولاً.'
                ) % {'name': rec.name, 'charge': charged.charge_id.name})
        self.write({'state': 'cancel'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'fleet_branch_rental.action_report_fleet_rental_contract'
        ).report_action(self)

    # ------------------------------------------------------------------
    @api.model
    def _issue_for_assignment(self, vehicle, company, employee=False,
                              request=False, date_start=None):
        """يُصدر عقداً سارياً عند تخصيص مركبة لفرع - تُستدعى من موافقة
        الأسطول على طلب السيارة ومن تنفيذ طلب تغيير المركبة."""
        owner = self.env['res.company']._get_fleet_owner_company()
        if not owner or not vehicle or not company or company == owner:
            return self.browse()
        date_start = date_start or fields.Date.context_today(self)
        existing = self.sudo().search([
            ('vehicle_id', '=', vehicle.id),
            ('company_id', '=', company.id),
            ('state', '=', 'active'),
        ], limit=1)
        if existing:
            return existing
        # عقد سارٍ لمركبة عند فرع آخر يُنهى أولاً: السيارة انتقلت فعلاً.
        self.sudo().search([
            ('vehicle_id', '=', vehicle.id), ('state', '=', 'active'),
        ]).action_end(_('تسليم المركبة لفرع آخر'), date_start)
        return self.sudo().create({
            'company_id': company.id,
            'vehicle_id': vehicle.id,
            'employee_id': employee and employee.id or False,
            'recruitment_request_id': request and request.id or False,
            'date_start': date_start,
            'monthly_rate': vehicle.rental_monthly_rate,
        })

    @api.model
    def _end_for_vehicle(self, vehicle, reason=False, date_end=None):
        contracts = self.sudo().search([
            ('vehicle_id', '=', vehicle.id), ('state', '=', 'active')])
        return contracts.action_end(reason, date_end)
