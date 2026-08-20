# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetVehicleBranchTransferWizard(models.TransientModel):
    """معالج نقل سيارة لفرع آخر - تنفيذ فوري (بلا موافقة، طلب صريح)، مع
    تسجيل الحركة في fleet.vehicle.branch.history تلقائياً. الصلاحية
    مقصورة على قسم الأسطول فقط (انظر ir.model.access.csv)."""
    _name = 'fleet.vehicle.branch.transfer.wizard'
    _description = 'معالج نقل سيارة لفرع آخر'

    vehicle_id = fields.Many2one('fleet.vehicle', string='السيارة', required=True)
    current_company_id = fields.Many2one(
        'res.company', string='الفرع الحالي',
        related='vehicle_id.company_id', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='نقل إلى فرع', required=True,
    )
    note = fields.Char(string='ملاحظة')

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id:
            self.company_id = False

    def action_confirm_transfer(self):
        self.ensure_one()
        if not self.vehicle_id:
            raise UserError(_('يجب تحديد السيارة.'))
        if not self.company_id:
            raise UserError(_('يجب اختيار الفرع المراد النقل إليه.'))
        if self.company_id == self.vehicle_id.company_id:
            raise UserError(_('السيارة تابعة لهذا الفرع أصلاً.'))
        self.vehicle_id._open_branch_history(self.company_id, self.note)
        return {'type': 'ir.actions.act_window_close'}
