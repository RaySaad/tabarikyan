# -*- coding: utf-8 -*-
from odoo import _, models


class FleetVehicleChangeRequest(models.Model):
    _inherit = 'fleet.vehicle.change.request'

    # الحادث والعطل: السيارة تُسلَّم للأسطول فعلياً، وتتوقف أجرتها عن
    # الفرع من يوم التسليم. ولولا هذا النقل التلقائي لاعتمد إيقاف
    # الأجرة على تذكُّر أحدهم نقلها يدوياً - وهو أكثر خطأ متوقَّع في
    # هذا النظام: فرعٌ يُحمَّل أجرة سيارة ليست لديه.
    _FLEET_RETURN_TYPES = ('accident', 'breakdown')

    def action_confirm_receipt(self):
        res = super().action_confirm_receipt()
        owner = self.env['res.company']._get_fleet_owner_company()
        if not owner:
            return res
        for rec in self:
            vehicle = rec.current_vehicle_id
            if rec.request_type not in rec._FLEET_RETURN_TYPES or not vehicle:
                continue
            if vehicle.company_id == owner:
                continue
            vehicle.sudo()._open_branch_history(
                owner, _('تسليم للأسطول: %s') % rec.name)
            rec.message_post(body=_(
                'سُلِّمت المركبة %(vehicle)s لشركة الأسطول - توقفت أجرتها '
                'على الفرع من اليوم.'
            ) % {'vehicle': vehicle.display_name})
        return res
