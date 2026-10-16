# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta

from odoo import api, fields, models


class FleetDashboard(models.AbstractModel):
    """بيانات لوحة الأسطول - تُقرأ دفعةً واحدة من الواجهة.

    نموذج مجرَّد بلا جدول: اللوحة قراءة فقط ولا شيء يُخزَّن."""
    _name = 'fleet.dashboard'
    _description = 'لوحة مؤشرات الأسطول'

    @api.model
    def _month_bounds(self, month=None):
        today = fields.Date.context_today(self)
        ref = fields.Date.to_date(month) if month else today
        first = ref.replace(day=1)
        last = date(first.year, first.month,
                    calendar.monthrange(first.year, first.month)[1])
        return first, last

    @api.model
    def _last_months(self, first, back=5):
        """قائمة أوائل الأشهر من الأقدم إلى شهر اللوحة."""
        months, year, month = [], first.year, first.month
        for _i in range(back + 1):
            months.append(date(year, month, 1))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        return list(reversed(months))

    @api.model
    def _trend(self, first):
        """تكاليف ستة أشهر - تُجمَّع في بايثون من قراءة واحدة لكل نموذج
        بدل استعلام لكل شهر."""
        months = self._last_months(first)
        start = months[0]
        end = date(first.year, first.month,
                   calendar.monthrange(first.year, first.month)[1])
        index = {m: i for i, m in enumerate(months)}
        series = {k: [0.0] * len(months)
                  for k in ('rent', 'service', 'fuel', 'accident')}

        def bucket(key, day, amount):
            slot = index.get(day.replace(day=1)) if day else None
            if slot is not None:
                series[key][slot] += amount or 0.0

        for charge in self.env['fleet.branch.rental.charge'].sudo().search([
                ('period_date', '>=', start), ('period_date', '<=', end),
                ('state', '=', 'posted')]):
            bucket('rent', charge.period_date, charge.amount_total)
        for service in self.env['fleet.vehicle.log.services'].sudo().search([
                ('date', '>=', start), ('date', '<=', end)]):
            bucket('service', service.date, service.amount)
        for log in self.env['fleet.fuel.log'].sudo().search([
                ('date', '>=', start), ('date', '<=', end)]):
            bucket('fuel', log.date, log.amount)
        for report in self.env['fleet.accident.report'].sudo().search([
                ('accident_date', '>=', start), ('accident_date', '<=', end)]):
            bucket('accident', report.accident_date, report.actual_cost)

        series['labels'] = ['%02d/%s' % (m.month, m.year) for m in months]
        return series

    @api.model
    def get_dashboard_data(self, month=None, branch_id=None):
        first, last = self._month_bounds(month)
        branch = self.env['res.company'].browse(int(branch_id)) \
            if branch_id else self.env['res.company']
        Vehicle = self.env['fleet.vehicle'].sudo()
        Contract = self.env['fleet.rental.contract'].sudo()
        Plan = self.env['fleet.maintenance.plan'].sudo()
        Report = self.env['fleet.accident.report'].sudo()
        Charge = self.env['fleet.branch.rental.charge'].sudo()
        Service = self.env['fleet.vehicle.log.services'].sudo()

        vehicles = Vehicle.search([])
        # الفلتر يقصر كل ما يُشتق من المركبات على فرع واحد. المركبة
        # الراكدة بلا فرع، فاختيار فرع يُخرجها - وهذا هو المقصود.
        if branch:
            vehicles = vehicles.filtered(
                lambda v: v.rental_branch_id.id == branch.id)
        chargeable = vehicles.filtered('rental_chargeable')
        rented = chargeable.filtered('rental_contract_id')
        idle = chargeable.filtered('is_rental_idle')

        # -- أجرة الشهر: المرحَّل والمتوقَّع -----------------------------
        charge_domain = [('period_date', '=', first), ('state', '!=', 'cancel')]
        if branch:
            charge_domain.append(('company_id', '=', branch.id))
        charges = Charge.search(charge_domain)
        posted = charges.filtered(lambda c: c.state == 'posted')
        contract_domain = [('state', '=', 'active'), ('date_start', '<=', last)]
        if branch:
            contract_domain.append(('company_id', '=', branch.id))
        expected_rate = sum(
            c.monthly_rate for c in Contract.search(contract_domain))

        # -- الصيانة ------------------------------------------------------
        plan_domain = [('vehicle_id', 'in', vehicles.ids)] if branch else []
        plans = Plan.search(plan_domain)
        overdue = plans.filtered(lambda p: p.state == 'overdue')
        warning = plans.filtered(lambda p: p.state == 'warning')

        # -- الحوادث والتكاليف --------------------------------------------
        accident_domain = [('accident_date', '>=', first),
                           ('accident_date', '<=', last)]
        service_domain = [('date', '>=', first), ('date', '<=', last)]
        fuel_domain = [('date', '>=', first), ('date', '<=', last)]
        if branch:
            accident_domain.append(('vehicle_id', 'in', vehicles.ids))
            service_domain.append(('vehicle_id', 'in', vehicles.ids))
            fuel_domain.append(('company_id', '=', branch.id))
        accidents = Report.search(accident_domain)
        services = Service.search(service_domain)
        service_cost = sum(services.mapped('amount'))

        # الوقود على الفروع لا على الأسطول - يُعرض للمراقبة لا كتكلفة
        # على شركة الأسطول.
        fuel = self.env['fleet.fuel.log'].sudo().search(fuel_domain)
        fuel_liters = sum(fuel.mapped('liters'))
        measured = fuel.filtered(lambda f: f.consumption > 0)
        avg_consumption = (
            sum(measured.mapped('consumption')) / len(measured)) if measured else 0.0

        # -- توزيع المركبات على الفروع ------------------------------------
        by_branch = {}
        for vehicle in rented:
            label = vehicle.rental_branch_id.display_name or '-'
            by_branch[label] = by_branch.get(label, 0) + 1

        # -- أعلى المركبات تكلفة في الشهر ----------------------------------
        cost_by_vehicle = {}
        for service in services:
            key = service.vehicle_id
            cost_by_vehicle[key] = cost_by_vehicle.get(key, 0.0) + (service.amount or 0.0)
        top = sorted(cost_by_vehicle.items(), key=lambda kv: kv[1], reverse=True)[:5]

        # -- مقارنة بالشهر السابق -------------------------------------------
        prev_last = first - timedelta(days=1)
        prev_first = prev_last.replace(day=1)
        prev_cost = sum(Service.search([
            ('date', '>=', prev_first), ('date', '<=', prev_last),
        ]).mapped('amount')) + sum(Report.search([
            ('accident_date', '>=', prev_first), ('accident_date', '<=', prev_last),
        ]).mapped('actual_cost'))
        cost_total = service_cost + sum(accidents.mapped('actual_cost'))
        growth = round(
            (cost_total - prev_cost) * 100.0 / prev_cost, 1) if prev_cost else 0.0

        # -- العمليات العالقة -----------------------------------------------
        open_accidents = Report.search(
            [('state', '!=', 'closed')] +
            ([('vehicle_id', 'in', vehicles.ids)] if branch else []))
        unpriced = open_accidents.filtered(lambda r: not r.actual_cost)
        pending_charges = charges.filtered(lambda c: c.state != 'posted')
        active_contracts = Contract.search(
            [('state', '=', 'active')] +
            ([('company_id', '=', branch.id)] if branch else []))

        # طابور طلبات السيارات من التوظيف: كان لا يظهر في اللوحة أصلاً
        # رغم أنه أكثر ما ينتظر الأسطول فيه قراراً.
        car_requests = self.env['recruitment.request'].sudo().search([
            ('car_requested', '=', True),
            ('car_request_state', 'in', ('requested', 'waiting', 'received')),
            ('state', 'not in', ('done', 'rejected')),
        ] + ([('company_id', '=', branch.id)] if branch else []))
        oldest_wait = max(car_requests.mapped('car_waiting_days') or [0])

        pipeline = [{
            'key': 'car_requests',
            'label': 'طلبات سيارات من التوظيف',
            'count': len(car_requests),
            'amount': 0.0,
            'hint': ('أقدمها منتظر %s يوماً' % oldest_wait) if car_requests
                    else 'لا طلبات معلّقة',
            'tone': 'cyan',
        }, {
            'key': 'contracts',
            'label': 'عقود سارية',
            'count': len(active_contracts),
            'amount': sum(active_contracts.mapped('monthly_rate')),
            'hint': 'أجرة شهرية متعاقَد عليها',
            'tone': 'blue',
        }, {
            'key': 'accidents',
            'label': 'بلاغات حوادث مفتوحة',
            'count': len(open_accidents),
            'amount': sum(open_accidents.mapped('actual_cost')),
            'hint': 'لم تُغلق بعد',
            'tone': 'red',
        }, {
            'key': 'unpriced',
            'label': 'بلاغات بلا تكلفة فعلية',
            'count': len(unpriced),
            'amount': 0.0,
            'hint': 'تنتظر تسعير الإصلاح',
            'tone': 'amber',
        }, {
            'key': 'charges',
            'label': 'تحميلات شهرية غير مرحَّلة',
            'count': len(pending_charges),
            'amount': sum(pending_charges.mapped('amount_total')),
            'hint': 'مسودة أو معتمَدة لم تُرحَّل',
            'tone': 'violet',
        }]

        # -- تنبيهات: لا تظهر إلا حين يكون فيها عمل --------------------------
        alerts = []
        if overdue:
            alerts.append({
                'key': 'overdue', 'tone': 'red', 'icon': 'fa-wrench',
                'title': 'صيانة تجاوزت موعدها',
                'text': '%s خطة صيانة تجاوزت الاستحقاق والمركبة تعمل.' % len(overdue),
                'action': 'openDue', 'button': 'عرض الخطط',
            })
        if idle:
            lost = sum(idle.mapped('rental_monthly_rate'))
            alerts.append({
                'key': 'idle', 'tone': 'amber', 'icon': 'fa-pause-circle',
                'title': 'مركبات راكدة بلا عقد',
                # ذكر أجرة ضائعة = صفر يشوّش، فتُذكر حين تكون لها قيمة.
                'text': ('%s مركبة بلا فرع مستأجر، وأجرتها الشهرية الضائعة %s.'
                         % (len(idle), round(lost, 2))) if lost else
                        ('%s مركبة بلا فرع مستأجر.' % len(idle)),
                'action': 'openIdle', 'button': 'عرض المركبات',
            })
        if active_contracts and not posted:
            alerts.append({
                'key': 'charge', 'tone': 'blue', 'icon': 'fa-file-text-o',
                'title': 'تحميل الشهر لم يُرحَّل',
                'text': 'لا يوجد تحميل مُرحَّل لشهر %02d/%s رغم وجود %s عقداً سارياً.' % (
                    first.month, first.year, len(active_contracts)),
                'action': 'openCharges', 'button': 'فتح التحميلات',
            })
        if unpriced:
            alerts.append({
                'key': 'unpriced', 'tone': 'violet', 'icon': 'fa-exclamation-triangle',
                'title': 'بلاغات تنتظر التسعير',
                'text': '%s بلاغاً بلا تكلفة فعلية، فلا يُحمَّل على الفرع.' % len(unpriced),
                'action': 'openAccidents', 'button': 'عرض البلاغات',
            })

        # -- أحدث الحركات ----------------------------------------------------
        recent = []
        for contract in Contract.search([], limit=10):
            recent.append({
                'type': 'contract', 'type_label': 'عقد تأجير',
                'name': contract.name, 'ref': contract.vehicle_id.display_name,
                'date': fields.Date.to_string(contract.date_start),
                'amount': contract.monthly_rate, 'state': contract.state,
                'state_label': dict(Contract._fields['state'].selection).get(
                    contract.state, contract.state),
                'model': 'fleet.rental.contract', 'id': contract.id,
            })
        for report in Report.search([], limit=10):
            recent.append({
                'type': 'accident', 'type_label': 'بلاغ حادث',
                'name': report.name, 'ref': report.vehicle_id.display_name,
                'date': fields.Date.to_string(report.accident_date),
                'amount': report.actual_cost, 'state': report.state,
                'state_label': dict(Report._fields['state'].selection).get(
                    report.state, report.state),
                'model': 'fleet.accident.report', 'id': report.id,
            })
        for charge in Charge.search([], limit=10):
            recent.append({
                'type': 'charge', 'type_label': 'تحميل شهري',
                'name': charge.name, 'ref': charge.company_id.display_name,
                'date': fields.Date.to_string(charge.period_date),
                'amount': charge.amount_total, 'state': charge.state,
                'state_label': dict(Charge._fields['state'].selection).get(
                    charge.state, charge.state),
                'model': 'fleet.branch.rental.charge', 'id': charge.id,
            })
        for log in self.env['fleet.fuel.log'].sudo().search([], limit=10):
            recent.append({
                'type': 'fuel', 'type_label': 'تعبئة وقود',
                'name': log.vehicle_id.display_name,
                'ref': log.company_id.display_name,
                'date': fields.Date.to_string(log.date),
                'amount': log.amount, 'state': 'done', 'state_label': 'مسجَّل',
                'model': 'fleet.fuel.log', 'id': log.id,
            })
        recent.sort(key=lambda r: r['date'] or '', reverse=True)

        currency = self.env.company.currency_id

        return {
            'period': {
                'from': fields.Date.to_string(first),
                'to': fields.Date.to_string(last),
                'label': '%02d/%s' % (first.month, first.year),
            },
            'branches': [{
                'id': company.id, 'name': company.display_name,
            } for company in Contract.search(
                [('state', '=', 'active')]).mapped('company_id')],
            'branch_id': branch.id or 0,
            'currency': {
                'symbol': currency.symbol or '',
                'position': currency.position,
            },
            'pipeline': pipeline,
            'alerts': alerts,
            'trend': self._trend(first),
            'recent': recent[:10],
            'kpi': {
                'vehicles': len(vehicles),
                'chargeable': len(chargeable),
                'rented': len(rented),
                'idle': len(idle),
                'utilisation': round(
                    len(rented) * 100.0 / len(chargeable), 1) if chargeable else 0.0,
                'idle_days_total': sum(idle.mapped('rental_idle_days')),
                'overdue_maintenance': len(overdue),
                'warning_maintenance': len(warning),
                'accidents': len(accidents),
                'accidents_cost': sum(accidents.mapped('actual_cost')),
                'service_cost': service_cost,
                'fuel_cost': sum(fuel.mapped('amount')),
                'fuel_liters': round(fuel_liters, 1),
                'avg_consumption': round(avg_consumption, 2),
                'rent_posted': sum(posted.mapped('amount_total')),
                'rent_expected': expected_rate,
                'charges_draft': len(charges) - len(posted),
                'cost_total': cost_total,
                'growth_rate': growth,
            },
            'by_branch': [{'label': k, 'value': v} for k, v in sorted(
                by_branch.items(), key=lambda kv: kv[1], reverse=True)],
            'top_cost': [{
                'label': vehicle.display_name,
                'value': round(amount, 2),
            } for vehicle, amount in top],
            'idle_list': [{
                'id': vehicle.id,
                'name': vehicle.display_name,
                'days': vehicle.rental_idle_days,
                'rate': vehicle.rental_monthly_rate,
            } for vehicle in idle.sorted(
                key=lambda v: v.rental_idle_days, reverse=True)[:8]],
            'due_list': [{
                'id': plan.id,
                'name': plan.name,
                'state': plan.state,
                'remaining_km': int(plan.remaining_km),
                'remaining_days': plan.remaining_days,
                'by_km': bool(plan.interval_km),
                'by_date': bool(plan.interval_days),
            } for plan in (overdue + warning).sorted(
                key=lambda p: (p.state != 'overdue', p.remaining_km))[:8]],
        }
