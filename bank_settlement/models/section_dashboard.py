# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class BankSettlementSectionDashboard(models.AbstractModel):
    """صفحة أقسام السداد ولوحة كل قسم على حدة.

    اللوحة الشاملة تحسب بـsudo لأنها نظرة إدارية جامعة. أما لوحات
    الأقسام فتُحسب **بصلاحيات المستخدم نفسه**: موظف السلف لا يجوز أن
    يعرف إجمالي الرسوم الحكومية ولو رقماً مجرَّداً، ولا أن يرى في
    مؤشراته سجلات تحجبها عنه قواعد السجلات. حين تُحسب الأرقام بصلاحيته
    تتطابق اللوحة مع ما يفتحه بيده، ولا يتسرّب شيء.
    """
    _inherit = 'bank.settlement.dashboard'

    # خريطة الأقسام: لكل قسم نموذجه وحقوله وحالاته.
    # الحالات تختلف بين النماذج فعلاً (السلفة تنتهي بـpaid وغيرها بـdone،
    # والسلفة وحدها لها مرحلتا موافقة قبل الصرف) - فتُوصَف هنا بدل
    # افتراض توحّدها.
    _SECTION_SPEC = {
        'advance': {
            'name': 'السلف',
            'model': 'bank.settlement.advance',
            'action': 'bank_settlement.action_bank_settlement_advance',
            'icon': 'fa-handshake-o',
            'tone': 'violet',
            'amount_field': 'amount',
            'date_field': 'transfer_date',
            'done_state': 'paid',
            'pending_states': ('waiting_approval', 'pm_approved', 'approved'),
        },
        'government_fee': {
            'name': 'الرسوم الحكومية',
            'model': 'bank.settlement.government.fee',
            'action': 'bank_settlement.action_bank_settlement_government_fee',
            'icon': 'fa-building-o',
            'tone': 'cyan',
            'amount_field': 'total_amount',
            'date_field': 'transfer_date',
            'done_state': 'done',
            'pending_states': ('under_review', 'confirmed'),
        },
        'vehicle_transfer': {
            'name': 'تحويلات المركبات',
            'model': 'bank.settlement.vehicle.transfer',
            'action': 'bank_settlement.action_bank_settlement_vehicle_transfer',
            'icon': 'fa-car',
            'tone': 'amber',
            'amount_field': 'amount',
            'date_field': 'transfer_date',
            'done_state': 'done',
            'pending_states': ('under_review', 'confirmed'),
        },
        'medical_insurance': {
            'name': 'التأمين الطبي',
            'model': 'bank.settlement.medical.insurance',
            'action': 'bank_settlement.action_bank_settlement_medical_insurance',
            'icon': 'fa-heartbeat',
            'tone': 'green',
            'amount_field': 'amount',
            'date_field': 'transfer_date',
            'done_state': 'done',
            'pending_states': ('under_review', 'confirmed'),
        },
        'representative': {
            'name': 'تصفيات المناديب',
            'model': 'bank.settlement.representative',
            'action': 'bank_settlement.action_bank_settlement_representative',
            'icon': 'fa-users',
            'tone': 'red',
            'amount_field': 'amount',
            'date_field': 'date',
            'done_state': 'done',
            'pending_states': ('under_review', 'confirmed'),
        },
    }

    # ------------------------------------------------------------------
    def _section_model(self, key):
        spec = self._SECTION_SPEC.get(key)
        if not spec:
            raise AccessError(_('قسم غير معروف: %s') % key)
        return self.env[spec['model']], spec

    def _can_read_section(self, key):
        """هل يملك المستخدم قراءة نموذج هذا القسم؟"""
        spec = self._SECTION_SPEC.get(key)
        if not spec:
            return False
        return self.env[spec['model']].has_access('read')

    def _currency_info(self):
        currency = self.env.company.currency_id
        return {
            'symbol': currency.symbol or 'ر.س',
            'position': currency.position or 'after',
            'decimals': currency.decimal_places or 2,
        }

    # ------------------------------------------------------------------
    @api.model
    def get_sections(self):
        """بطاقات الصفحة الرئيسية للتطبيق - ما يراه هذا المستخدم فقط.

        الإخفاء هنا ليس تجميلاً: البطاقة تُبنى من صلاحية النموذج نفسها،
        فلا تظهر بطاقة لقسم لا يملك فتحه."""
        sections = []
        for key, spec in self._SECTION_SPEC.items():
            if not self._can_read_section(key):
                continue
            model = self.env[spec['model']]
            pending = model.search([('state', 'in', list(spec['pending_states']))])
            sections.append({
                'key': key,
                'name': spec['name'],
                'icon': spec['icon'],
                'tone': spec['tone'],
                'pending_count': len(pending),
                'pending_amount': sum(pending.mapped(spec['amount_field'])),
                'total_count': model.search_count([]),
            })

        extras = []
        # اللوحة الشاملة: لمن يملك رؤية كل الأقسام - لا لمن يرى قسماً.
        if all(self._can_read_section(key) for key in self._SECTION_SPEC):
            extras.append({
                'key': 'overview', 'name': 'اللوحة الشاملة',
                'icon': 'fa-th-large', 'tone': 'blue',
                'action': 'bank_settlement.action_bank_settlement_dashboard',
            })
        if self.env['bank.settlement.employee.statement.wizard'].has_access('create'):
            extras.append({
                'key': 'statement', 'name': 'كشف حساب موظف',
                'icon': 'fa-file-text-o', 'tone': 'cyan',
                'action': 'bank_settlement.action_bank_settlement_employee_statement_wizard',
            })
        return {
            'sections': sections,
            'extras': extras,
            'currency': self._currency_info(),
            'user_name': self.env.user.name,
        }

    # ------------------------------------------------------------------
    @api.model
    def get_section_data(self, section, period='this_month'):
        """مؤشرات قسم واحد - بصلاحيات المستخدم لا بـsudo."""
        model, spec = self._section_model(section)
        if not self._can_read_section(section):
            raise AccessError(_('لا تملك صلاحية الاطلاع على قسم %s.') % spec['name'])

        amount_field = spec['amount_field']
        date_field = spec['date_field']
        start, end, prev_start, prev_end = self._section_period(period)

        def _sum(records):
            return sum(records.mapped(amount_field))

        done = model.search([
            ('state', '=', spec['done_state']),
            (date_field, '>=', start), (date_field, '<=', end),
        ])
        prev_done = model.search([
            ('state', '=', spec['done_state']),
            (date_field, '>=', prev_start), (date_field, '<=', prev_end),
        ])
        done_amount, prev_amount = _sum(done), _sum(prev_done)
        growth = round((done_amount - prev_amount) * 100.0 / prev_amount, 1) \
            if prev_amount else 0.0

        # -- توزيع الحالات: مصدر الرسم ومصدر البطاقات معاً --------------
        selection = dict(model._fields['state'].selection)
        by_state = []
        for state_key, label in selection.items():
            records = model.search([('state', '=', state_key)])
            if not records:
                continue
            by_state.append({
                'state': state_key, 'label': label,
                'count': len(records), 'amount': _sum(records),
            })

        pending = model.search([('state', 'in', list(spec['pending_states']))])
        returned = model.search_count([('returned_for_correction', '=', True)]) \
            if 'returned_for_correction' in model._fields else 0

        # -- اتجاه ستة أشهر ---------------------------------------------
        months, labels, series = [], [], []
        first = fields.Date.context_today(self).replace(day=1)
        for offset in range(5, -1, -1):
            month_start = first - relativedelta(months=offset)
            month_end = month_start + relativedelta(months=1, days=-1)
            months.append((month_start, month_end))
            labels.append('%02d/%s' % (month_start.month, month_start.year))
        for month_start, month_end in months:
            series.append(_sum(model.search([
                ('state', '=', spec['done_state']),
                (date_field, '>=', month_start), (date_field, '<=', month_end),
            ])))

        return {
            'section': section,
            'name': spec['name'],
            'icon': spec['icon'],
            'tone': spec['tone'],
            'action': spec['action'],
            'currency': self._currency_info(),
            'period': {'label': self._section_period_label(period), 'key': period},
            'kpi': {
                'done_amount': done_amount,
                'done_count': len(done),
                'growth': growth,
                'pending_count': len(pending),
                'pending_amount': _sum(pending),
                'returned_count': returned,
                'total_count': model.search_count([]),
            },
            'by_state': by_state,
            'trend': {'labels': labels, 'values': series},
            'recent': self._section_recent(model, spec),
            'pending_list': self._section_rows(
                pending.sorted(key=lambda r: r.id, reverse=True)[:8], spec),
        }

    # ------------------------------------------------------------------
    def _section_recent(self, model, spec):
        records = model.search([], order='create_date desc', limit=8)
        return self._section_rows(records, spec)

    def _section_rows(self, records, spec):
        selection = dict(records._fields['state'].selection) if records else {}
        rows = []
        for record in records:
            party = False
            for field in ('employee_id', 'partner_id', 'vendor_id'):
                if field in record._fields and record[field]:
                    party = record[field].display_name
                    break
            rows.append({
                'id': record.id,
                'model': spec['model'],
                'name': record.display_name,
                'party': party or '-',
                'date': fields.Date.to_string(record[spec['date_field']])
                        if record[spec['date_field']] else '',
                'amount': record[spec['amount_field']],
                'state': record.state,
                'state_label': selection.get(record.state, record.state),
            })
        return rows

    # ------------------------------------------------------------------
    def _section_period(self, period):
        """حدود الفترة الحالية والسابقة - الفترة السابقة بنفس الطول."""
        today = fields.Date.context_today(self)
        if period == 'this_year':
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            prev_start = start - relativedelta(years=1)
            prev_end = end - relativedelta(years=1)
        elif period == 'last_month':
            start = (today.replace(day=1) - relativedelta(months=1))
            end = today.replace(day=1) - relativedelta(days=1)
            prev_start = start - relativedelta(months=1)
            prev_end = start - relativedelta(days=1)
        elif period == 'all':
            start = fields.Date.to_date('2000-01-01')
            end = today
            prev_start, prev_end = start, start
        else:  # this_month
            start = today.replace(day=1)
            end = start + relativedelta(months=1, days=-1)
            prev_start = start - relativedelta(months=1)
            prev_end = start - relativedelta(days=1)
        return start, end, prev_start, prev_end

    def _section_period_label(self, period):
        return {
            'this_month': 'هذا الشهر',
            'last_month': 'الشهر الماضي',
            'this_year': 'هذه السنة',
            'all': 'كل الأوقات',
        }.get(period, 'هذا الشهر')
