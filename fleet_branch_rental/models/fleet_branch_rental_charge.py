# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FleetBranchRentalCharge(models.Model):
    """تحميل أجرة الأسطول على فرع عن شهر محدَّد.

    لا تقدير في هذا المستند: أيام تبعية كل مركبة للفرع مأخوذة من
    "تاريخ فروع السيارات" (fleet.vehicle.branch.history) الذي يكتبه
    معالج النقل بتاريخه - فتسليم السيارة للأسطول عند حادث أو عطل كبير
    يُغلق الفترة ويوقف الأجرة من يومه بلا تدخل.

    سطران فقط:
    - أجرة: الأجرة اليومية × أيام التبعية.
    - تلفيات: تكلفة الإصلاح الفعلية × نسبة تحمّل الفرع - ولا يدخل هنا
      إلا ما له بلاغ (حادث رسمي أو تلفيات بسيطة)؛ الصيانة الدورية
      والأعطال على الأسطول داخل الأجرة.
    """
    _name = 'fleet.branch.rental.charge'
    _description = 'تحميل أجرة الأسطول على فرع'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_date desc, id desc'

    name = fields.Char(
        string='الكود', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    company_id = fields.Many2one(
        'res.company', string='الفرع المحمَّل', required=True, tracking=True,
        default=lambda self: self.env.company,
        help='الفرع الذي استعمل المركبات - لا شركة الأسطول نفسها.',
    )
    fleet_company_id = fields.Many2one(
        'res.company', string='شركة الأسطول', readonly=True,
        default=lambda self: self.env['res.company']._get_fleet_owner_company(),
    )
    period_date = fields.Date(
        string='الشهر', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help='أي تاريخ داخل الشهر المراد تحميله - يُضبط على أوله تلقائياً.',
    )
    date_from = fields.Date(string='من', compute='_compute_period_bounds', store=True)
    date_to = fields.Date(string='إلى', compute='_compute_period_bounds', store=True)

    line_ids = fields.One2many(
        'fleet.branch.rental.charge.line', 'charge_id', string='السطور',
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    amount_rent = fields.Monetary(
        string='إجمالي الأجرة', compute='_compute_amounts', store=True)
    amount_damage = fields.Monetary(
        string='إجمالي التلفيات', compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(
        string='الإجمالي', compute='_compute_amounts', store=True, tracking=True)

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('confirmed', 'معتمَد'),
            ('posted', 'مُرحَّل'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )
    move_branch_id = fields.Many2one(
        'account.move', string='قيد الفرع', readonly=True, copy=False)
    move_fleet_id = fields.Many2one(
        'account.move', string='قيد الأسطول', readonly=True, copy=False)
    note = fields.Text(string='ملاحظات')

    # ------------------------------------------------------------------
    @api.depends('period_date')
    def _compute_period_bounds(self):
        for rec in self:
            if not rec.period_date:
                rec.date_from = rec.date_to = False
                continue
            first = rec.period_date.replace(day=1)
            last_day = calendar.monthrange(first.year, first.month)[1]
            rec.date_from = first
            rec.date_to = date(first.year, first.month, last_day)

    @api.depends('line_ids.amount', 'line_ids.line_type')
    def _compute_amounts(self):
        for rec in self:
            rent = sum(rec.line_ids.filtered(lambda l: l.line_type == 'rent').mapped('amount'))
            damage = sum(rec.line_ids.filtered(lambda l: l.line_type == 'damage').mapped('amount'))
            rec.amount_rent = rent
            rec.amount_damage = damage
            rec.amount_total = rent + damage

    @api.constrains('company_id', 'period_date')
    def _check_unique_period(self):
        """تحميلان لنفس الفرع عن نفس الشهر = ازدواج في القيود."""
        for rec in self:
            if rec.state == 'cancel':
                continue
            twin = self.sudo().search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('period_date', '=', rec.period_date),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if twin:
                raise ValidationError(_(
                    'يوجد تحميل لهذا الفرع عن الشهر نفسه: %s.'
                ) % twin.name)

    @api.constrains('company_id', 'fleet_company_id')
    def _check_not_fleet_company(self):
        for rec in self:
            if rec.fleet_company_id and rec.company_id == rec.fleet_company_id:
                raise ValidationError(_(
                    'شركة الأسطول لا تُحمَّل أجرةً على نفسها.'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('period_date'):
                vals['period_date'] = fields.Date.to_date(vals['period_date']).replace(day=1)
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'fleet.branch.rental.charge') or _('جديد')
            if not vals.get('fleet_company_id'):
                owner = self.env['res.company']._get_fleet_owner_company()
                vals['fleet_company_id'] = owner.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('period_date'):
            vals['period_date'] = fields.Date.to_date(vals['period_date']).replace(day=1)
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    'لا يمكن حذف تحميل مُرحَّل (%s) - ألغِه ليُعكس قيداه.'
                ) % rec.name)
        return super().unlink()

    # ------------------------------------------------------------------
    # توليد السطور
    # ------------------------------------------------------------------
    def _effective_date_from(self):
        """بداية الاحتساب: أول الشهر أو تاريخ بدء التطبيق، أيهما أحدث -
        فالبيانات الأقدم تبقى سجلات تدقيق بلا أثر محاسبي (طلب صريح)."""
        self.ensure_one()
        owner = self.fleet_company_id or self.env['res.company']._get_fleet_owner_company()
        start = owner.fleet_rental_start_date if owner else False
        if start and start > self.date_from:
            return start
        return self.date_from

    def action_generate_lines(self):
        """يبني السطور من الوقائع المسجَّلة - لا يُدخل المستخدم رقماً."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('التوليد متاح في حالة "مسودة" فقط.'))
            rec.line_ids.unlink()
            rec._generate_rent_lines()
            rec._generate_damage_lines()
            if not rec.line_ids:
                rec.message_post(body=_(
                    'لا توجد وقائع قابلة للتحميل في هذا الشهر.'))
        return True

    def _generate_rent_lines(self):
        """الأجرة من عقود التأجير: العقد هو سجل الاستخدام، والملكية
        تبقى لشركة الأسطول فلا تُقاس الأجرة بحركة ملكية."""
        self.ensure_one()
        start, end = self._effective_date_from(), self.date_to
        if start > end:
            return
        days_in_month = calendar.monthrange(
            self.date_from.year, self.date_from.month)[1]
        contracts = self.env['fleet.rental.contract'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('active', 'ended')),
            ('date_start', '<=', end),
            '|', ('date_end', '=', False), ('date_end', '>=', start),
        ], order='vehicle_id, date_start')
        for contract in contracts:
            vehicle = contract.vehicle_id
            if not vehicle.rental_chargeable or contract.monthly_rate <= 0:
                continue
            # الفترة [التسليم، الإرجاع) - يوم الإرجاع لا يُحتسب على الفرع،
            # فهو أول يوم عند الأسطول أو عند الفرع التالي؛ ولولا ذلك
            # لتضاعف يومٌ في كل تسليم.
            seg_start = max(contract.date_start, start)
            stop_exclusive = min(contract.date_end or (end + timedelta(days=1)),
                                 end + timedelta(days=1))
            days = (stop_exclusive - seg_start).days
            if days <= 0:
                continue
            daily = contract.monthly_rate / days_in_month
            self.env['fleet.branch.rental.charge.line'].create({
                'charge_id': self.id,
                'line_type': 'rent',
                'contract_id': contract.id,
                'vehicle_id': vehicle.id,
                'date_from': seg_start,
                'date_to': stop_exclusive - timedelta(days=1),
                'days': days,
                'monthly_rate': contract.monthly_rate,
                'amount': daily * days,
            })

    def _generate_damage_lines(self):
        self.ensure_one()
        reports = self.env['fleet.accident.report'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'closed'),
            ('close_date', '>=', self._effective_date_from()),
            ('close_date', '<=', self.date_to),
            ('actual_cost', '>', 0),
            ('branch_share_percent', '>', 0),
            ('rental_charge_line_id', '=', False),
        ])
        # بلاغ محجوز في تحميل آخر قائم (ولو مسودة) لا يُلتقط مرتين -
        # الحجز النهائي يقع عند الترحيل، وبينهما قد يُولَّد تحميل آخر.
        taken = self.env['fleet.branch.rental.charge.line'].sudo().search([
            ('line_type', '=', 'damage'),
            ('accident_report_id', 'in', reports.ids),
            ('charge_id.state', '!=', 'cancel'),
        ]).mapped('accident_report_id')
        reports -= taken
        for report in reports:
            self.env['fleet.branch.rental.charge.line'].create({
                'charge_id': self.id,
                'line_type': 'damage',
                'vehicle_id': report.vehicle_id.id,
                'accident_report_id': report.id,
                'cost': report.actual_cost,
                'share_percent': report.branch_share_percent,
                'amount': report.actual_cost * report.branch_share_percent / 100.0,
            })

    # ------------------------------------------------------------------
    # الاعتماد والترحيل
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('الاعتماد من حالة "مسودة" فقط.'))
            if not rec.line_ids:
                raise UserError(_('لا سطور في هذا التحميل - ولّدها أولاً.'))
        self.write({'state': 'confirmed'})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    'التحميل مُرحَّل - ألغِه ليُعكس قيداه بدل إعادته لمسودة.'))
        self.write({'state': 'draft'})

    def _get_account(self, company, fname, label):
        account = company._get_fleet_rental_config(fname)
        if not account:
            raise UserError(_(
                'لم يُحدَّد "%(label)s" في إعدادات شركة "%(company)s". '
                'يحدّده المحاسب من الإعدادات قبل أول ترحيل.'
            ) % {'label': label, 'company': company.display_name})
        return account

    def _prepare_move_lines(self, debit_account, credit_account, label,
                            analytic=False, company=False):
        """سطر مدين لكل حساب تحليلي (عند طلب التحليل) مقابل سطر دائن
        واحد - فتظهر تكلفة كل منصة في تقاريرها."""
        self.ensure_one()
        lines = []
        if analytic:
            groups = {}
            for line in self.line_ids:
                key = str(line._get_analytic_distribution(company) or '')
                groups.setdefault(key, [0.0, line._get_analytic_distribution(company)])
                groups[key][0] += line.amount
            for amount, distribution in groups.values():
                if self.currency_id.is_zero(amount):
                    continue
                lines.append((0, 0, {
                    'name': label, 'account_id': debit_account.id,
                    'debit': amount, 'credit': 0.0,
                    'analytic_distribution': distribution or False,
                }))
        if not lines:
            lines.append((0, 0, {
                'name': label, 'account_id': debit_account.id,
                'debit': self.amount_total, 'credit': 0.0}))
        lines.append((0, 0, {
            'name': label, 'account_id': credit_account.id,
            'debit': 0.0, 'credit': self.amount_total}))
        return lines

    def action_post(self):
        """قيدان متقابلان: مصروف في الفرع، واسترداد في الأسطول.

        الرقم الضريبي واحد للمجموعة، فلا فاتورة ولا ضريبة - والحساب
        الجاري بين الفروع يتقاصّ عند توحيد الميزانية."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('الترحيل بعد الاعتماد فقط.'))
            if rec.currency_id.is_zero(rec.amount_total):
                raise UserError(_('لا يُرحَّل تحميل بمبلغ صفري.'))
            fleet = rec.fleet_company_id or self.env['res.company']._get_fleet_owner_company()
            if not fleet:
                raise UserError(_(
                    'لم تُحدَّد شركة الأسطول - فعّل "شركة الأسطول" على شركتها.'))

            label = _('أجرة أسطول %(month)s - %(branch)s') % {
                'month': rec.date_from.strftime('%m/%Y'),
                'branch': rec.company_id.display_name,
            }
            branch_move = self.env['account.move'].sudo().with_company(rec.company_id).create({
                'company_id': rec.company_id.id,
                'journal_id': rec._get_account(
                    rec.company_id, 'fleet_rental_journal_id', 'دفتر قيود التحميل').id,
                'date': rec.date_to,
                'ref': label,
                'line_ids': rec._prepare_move_lines(
                    rec._get_account(rec.company_id, 'fleet_rental_expense_account_id',
                                     'حساب مصروف أجرة السيارات'),
                    rec._get_account(rec.company_id, 'fleet_rental_interco_account_id',
                                     'الحساب الجاري بين الفروع'),
                    label, analytic=True, company=rec.company_id),
            })
            fleet_move = self.env['account.move'].sudo().with_company(fleet).create({
                'company_id': fleet.id,
                'journal_id': rec._get_account(
                    fleet, 'fleet_rental_journal_id', 'دفتر قيود التحميل').id,
                'date': rec.date_to,
                'ref': label,
                'line_ids': rec._prepare_move_lines(
                    rec._get_account(fleet, 'fleet_rental_interco_account_id',
                                     'الحساب الجاري بين الفروع'),
                    rec._get_account(fleet, 'fleet_rental_income_account_id',
                                     'حساب استرداد تكلفة الأسطول'),
                    label),
            })
            (branch_move | fleet_move).action_post()
            rec.write({
                'move_branch_id': branch_move.id,
                'move_fleet_id': fleet_move.id,
                'state': 'posted',
            })
            # ختم البلاغات: الترحيل هو لحظة الحسم، فلا يُحمَّل البلاغ
            # نفسه في شهر لاحق.
            for line in rec.line_ids.filtered(lambda l: l.accident_report_id):
                line.accident_report_id.sudo().rental_charge_line_id = line.id
            rec.message_post(body=_(
                'رُحِّل التحميل: %(amount)s - قيد الفرع %(b)s، قيد الأسطول %(f)s.'
            ) % {'amount': rec.amount_total, 'b': branch_move.name, 'f': fleet_move.name})
        return True

    def action_cancel(self):
        """الإلغاء بعد الترحيل يعكس القيدين - لا يحذفهما."""
        for rec in self:
            if rec.state == 'posted':
                moves = (rec.move_branch_id | rec.move_fleet_id).sudo()
                posted = moves.filtered(lambda m: m.state == 'posted')
                reversals = self.env['account.move']
                # قاموس لكل قيد: _reverse_moves تعكس بـzip مع القائمة،
                # فقاموس واحد لقيدين يعكس الأول ويترك الثاني مرحَّلاً -
                # أي تحميل ملغى محاسبياً في جهة وقائم في الأخرى.
                for move in posted:
                    reversals |= move.with_company(move.company_id)._reverse_moves([{
                        'date': fields.Date.context_today(rec),
                        'ref': _('عكس %s') % rec.name,
                    }], cancel=True)
                if reversals:
                    rec.message_post(body=_('عُكست القيود: %s') % ', '.join(
                        reversals.mapped('name')))
            rec.line_ids.mapped('accident_report_id').sudo().write(
                {'rental_charge_line_id': False})
            rec.state = 'cancel'
        return True

    def action_view_moves(self):
        self.ensure_one()
        moves = (self.move_branch_id | self.move_fleet_id)
        return {
            'name': _('قيود التحميل'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    # ------------------------------------------------------------------
    @api.model
    def action_generate_all_branches(self, period_date=None):
        """ينشئ تحميل الشهر لكل فرع له مركبات - زر واحد بدل سجل بسجل."""
        owner = self.env['res.company']._get_fleet_owner_company()
        if not owner:
            raise UserError(_('لم تُحدَّد شركة الأسطول.'))
        period = fields.Date.to_date(period_date) if period_date else \
            fields.Date.context_today(self).replace(day=1)
        period = period.replace(day=1)
        branches = self.env['res.company'].sudo().search([('id', '!=', owner.id)])
        created = self.browse()
        for branch in branches:
            existing = self.sudo().search([
                ('company_id', '=', branch.id), ('period_date', '=', period),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if existing:
                continue
            charge = self.create({'company_id': branch.id, 'period_date': period})
            charge.action_generate_lines()
            if charge.line_ids:
                created |= charge
            else:
                charge.unlink()
        return {
            'name': _('تحميلات الشهر'),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }


class FleetBranchRentalChargeLine(models.Model):
    _name = 'fleet.branch.rental.charge.line'
    _description = 'سطر تحميل أجرة الأسطول'
    _order = 'line_type, vehicle_id'

    charge_id = fields.Many2one(
        'fleet.branch.rental.charge', string='التحميل',
        required=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='charge_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(
        related='charge_id.currency_id', readonly=True)
    line_type = fields.Selection(
        selection=[('rent', 'أجرة'), ('damage', 'تلفيات وحوادث')],
        string='النوع', required=True, default='rent',
    )
    vehicle_id = fields.Many2one('fleet.vehicle', string='المركبة', required=True)
    contract_id = fields.Many2one(
        'fleet.rental.contract', string='العقد', ondelete='restrict')
    # سطر الأجرة
    date_from = fields.Date(string='من')
    date_to = fields.Date(string='إلى')
    days = fields.Integer(string='الأيام')
    monthly_rate = fields.Monetary(string='الأجرة الشهرية')
    # سطر التلفيات
    accident_report_id = fields.Many2one(
        'fleet.accident.report', string='البلاغ', ondelete='restrict')
    cost = fields.Monetary(string='تكلفة الإصلاح')
    share_percent = fields.Float(string='نسبة التحمل %')

    amount = fields.Monetary(string='المحمَّل', required=True)

    def _get_analytic_distribution(self, company):
        """حساب منصة المندوب التحليلي - فتدخل أجرة السيارة في ربحية
        المنصة كبقية تكاليفها، بدل أن تبقى خارج التحليل.

        يُتخطى الحساب التابع لشركة أخرى: أودو تمنع التداخل بين
        الشركات، ولا يصح أن يسقط القيد كله لأجل بُعد تحليلي.
        """
        self.ensure_one()
        employee = self.contract_id.employee_id or self.accident_report_id.employee_id
        account = employee.sudo().project_id.account_id if employee else False
        if not account:
            return False
        if account.company_id and account.company_id != company:
            return False
        return {str(account.id): 100.0}
