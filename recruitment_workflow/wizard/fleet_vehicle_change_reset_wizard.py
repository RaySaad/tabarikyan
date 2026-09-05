# -*- coding: utf-8 -*-
from odoo import models, fields


class FleetVehicleChangeResetWizard(models.TransientModel):
    """معالج إرجاع طلب تغيير المركبة لمسودة - يفرض تسجيل سبب الإرجاع،
    بنفس مبدأ hr.employee.platform.transfer.reset.wizard: الإرجاع ممنوع
    بنقرة مباشرة على شريط الحالة ويمر حصراً عبر هذا المعالج."""
    _name = 'fleet.vehicle.change.reset.wizard'
    _description = 'معالج إرجاع طلب تغيير المركبة لمسودة'

    request_id = fields.Many2one(
        'fleet.vehicle.change.request', string='الطلب', required=True,
    )
    reason = fields.Text(
        string='سبب الإرجاع', required=True,
        help='وضّح سبب إعادة الطلب لمسودة (مثال: مرفقات ناقصة، مركبة بديلة خاطئة).',
    )

    def action_confirm_reset(self):
        self.ensure_one()
        self.request_id.action_reset_draft(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
