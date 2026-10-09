# -*- coding: utf-8 -*-
from odoo import _, fields, models


class FleetVehicleChangeRequest(models.Model):
    _inherit = 'fleet.vehicle.change.request'

    def action_confirm_receipt(self):
        """الاستلام الفعلي هو لحظة انتقال المركبة - فعنده ينتهي عقد
        القديمة ويصدر عقد الجديدة.

        الملكية لا تتحرك: المركبات تبقى في دفاتر الأسطول، والعقد وحده
        يقول من يستعملها - وعليه تُحتسب الأجرة. ولولا هذا الإنهاء
        التلقائي لبقي الفرع يُحمَّل أجرة سيارة سلّمها فعلاً.
        """
        res = super().action_confirm_receipt()
        Contract = self.env['fleet.rental.contract']
        for rec in self:
            today = rec.receipt_date or fields.Date.context_today(rec)
            if rec.current_vehicle_id:
                label = dict(rec._fields['request_type'].selection).get(
                    rec.request_type, rec.request_type)
                Contract._end_for_vehicle(
                    rec.current_vehicle_id,
                    '%s - %s' % (label, rec.name), today)
            if rec.new_vehicle_id and rec.employee_id:
                employee_company = rec.employee_id.sudo().company_id
                contract = Contract._issue_for_assignment(
                    rec.new_vehicle_id, employee_company,
                    employee=rec.employee_id, date_start=today)
                if contract:
                    rec.message_post(body=_(
                        'صدر عقد التأجير %s للمركبة الجديدة.') % contract.name)
        return res
