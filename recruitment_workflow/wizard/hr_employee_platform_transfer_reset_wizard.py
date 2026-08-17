# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployeePlatformTransferResetWizard(models.TransientModel):
    """معالج إرجاع طلب نقل المنصة لمسودة للتصحيح - يفرض تسجيل سبب الإرجاع،
    بنفس مبدأ recruitment.return.wizard (إرجاع طلب التوظيف لمرحلة سابقة):
    الإرجاع ممنوع بنقرة مباشرة على شريط الحالة، ويمر حصراً عبر هذا المعالج."""
    _name = 'hr.employee.platform.transfer.reset.wizard'
    _description = 'معالج إرجاع طلب نقل المنصة لمسودة'

    request_id = fields.Many2one(
        'hr.employee.platform.transfer.request', string='الطلب', required=True,
    )
    reason = fields.Text(
        string='سبب الإرجاع', required=True,
        help='وضّح سبب إعادة الطلب لمسودة (مثال: بيانات خاطئة، تراجع الموظف عن النقل).',
    )

    def action_confirm_reset(self):
        self.ensure_one()
        self.request_id.action_reset_draft(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
