# -*- coding: utf-8 -*-
import calendar
from datetime import date

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
    def get_dashboard_data(self, month=None):
        first, last = self._month_bounds(month)
        Vehicle = self.env['fleet.vehicle'].sudo()
        Contract = self.env['fleet.rental.contract'].sudo()
        Plan = self.env['fleet.maintenance.plan'].sudo()
        Report = self.env['fleet.accident.report'].sudo()
        Charge = self.env['fleet.branch.rental.charge'].sudo()
        Service = self.env['fleet.vehicle.log.services'].sudo()

        vehicles = Vehicle.search([])
        chargeable = vehicles.filtered('rental_chargeable')
        rented = chargeable.filtered('rental_contract_id')
        idle = chargeable.filtered('is_rental_idle')

        # -- أجرة الشهر: المرحَّل والمتوقَّع -----------------------------
        charges = Charge.search([
            ('period_date', '=', first), ('state', '!=', 'cancel')])
        posted = charges.filtered(lambda c: c.state == 'posted')
        expected_rate = sum(
            c.monthly_rate for c in Contract.search([
                ('state', '=', 'active'),
                ('date_start', '<=', last),
            ]))

        # -- الصيانة ------------------------------------------------------
        plans = Plan.search([])
        overdue = plans.filtered(lambda p: p.state == 'overdue')
        warning = plans.filtered(lambda p: p.state == 'warning')

        # -- الحوادث والتكاليف --------------------------------------------
        accidents = Report.search([
            ('accident_date', '>=', first), ('accident_date', '<=', last)])
        services = Service.search([
            ('date', '>=', first), ('date', '<=', last)])
        service_cost = sum(services.mapped('amount'))

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

        return {
            'period': {
                'from': fields.Date.to_string(first),
                'to': fields.Date.to_string(last),
                'label': '%02d/%s' % (first.month, first.year),
            },
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
                'rent_posted': sum(posted.mapped('amount_total')),
                'rent_expected': expected_rate,
                'charges_draft': len(charges) - len(posted),
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
