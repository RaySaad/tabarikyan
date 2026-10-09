# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class FleetRentalOpeningWizard(models.TransientModel):
    """عقود افتتاحية للمركبات التي هي بيد المناديب اليوم.

    النظام يبدأ وفيه سيارات وسائقون فقط، بلا عقود - فلا أساس لاحتساب
    أجرة. هذه الأداة تُنشئ لكل مركبة عقداً سارياً مع فرع سائقها
    الحالي بتاريخ بدء واحد، بدل إنشائها عقداً عقداً.
    """
    _name = 'fleet.rental.opening.wizard'
    _description = 'إنشاء عقود تأجير افتتاحية'

    date_start = fields.Date(
        string='تاريخ بدء العقود', required=True,
        default=lambda self: (
            self.env['res.company']._get_fleet_owner_company().fleet_rental_start_date
            or fields.Date.context_today(self)),
        help='عادةً نفس "بداية احتساب الأجرة" - فما قبله لا يُحمَّل أصلاً.',
    )
    vehicle_ids = fields.Many2many(
        'fleet.vehicle', string='مركبات محدَّدة',
        help='اتركه فارغاً لتشمل كل المركبات الخاضعة للتحميل.',
    )
    skipped_note = fields.Text(string='ما لم يُنشأ له عقد', readonly=True)

    def _candidate_vehicles(self):
        if self.vehicle_ids:
            return self.vehicle_ids
        return self.env['fleet.vehicle'].sudo().search([
            ('rental_chargeable', '=', True),
        ])

    def action_create_contracts(self):
        self.ensure_one()
        owner = self.env['res.company']._get_fleet_owner_company()
        if not owner:
            raise UserError(_(
                'لم تُحدَّد شركة الأسطول - فعّل "شركة الأسطول" على شركتها أولاً.'))

        Contract = self.env['fleet.rental.contract']
        created, skipped = Contract, []
        for vehicle in self._candidate_vehicles():
            if vehicle.rental_monthly_rate <= 0:
                skipped.append(_('%s: بلا أجرة شهرية') % vehicle.display_name)
                continue
            # نفس اشتقاق سير التوظيف لسائق المركبة (driver_id شريك لا
            # موظفاً في أودو القياسية) - بلا تكرار منطقه هنا.
            employee = vehicle._get_current_driver_employee()
            if not employee and vehicle.future_driver_id:
                employee = self.env['hr.employee'].sudo().search(
                    [('work_contact_id', '=', vehicle.future_driver_id.id)], limit=1)
            if not employee:
                skipped.append(_('%s: بلا سائق مرتبط بموظف') % vehicle.display_name)
                continue
            branch = employee.sudo().company_id
            if not branch or branch == owner:
                skipped.append(_('%s: سائقه بلا فرع (أو تابع للأسطول)')
                               % vehicle.display_name)
                continue
            contract = Contract._issue_for_assignment(
                vehicle, branch, employee=employee, date_start=self.date_start)
            if contract:
                created |= contract

        self.skipped_note = '\n'.join(skipped) or _('لا استثناءات.')
        if not created:
            raise UserError(_(
                'لم يُنشأ أي عقد.\n%s') % (self.skipped_note or ''))
        return {
            'name': _('العقود الافتتاحية (%s)') % len(created),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.rental.contract',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }
