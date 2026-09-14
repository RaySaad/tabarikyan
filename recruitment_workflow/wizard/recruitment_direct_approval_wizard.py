# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class RecruitmentDirectApprovalWizard(models.TransientModel):
    """معالج الاعتماد المباشر من الإدارة - يفرض تسجيل السبب، بنفس نمط
    recruitment.reject.wizard."""
    _name = 'recruitment.direct.approval.wizard'
    _description = 'مساعد الاعتماد المباشر لطلب التوظيف'

    request_id = fields.Many2one('recruitment.request', string='الطلب', required=True)
    reason = fields.Text(string='سبب الاعتماد المباشر', required=True)

    def action_confirm_direct_approval(self):
        self.ensure_one()
        if not self.reason:
            raise UserError(_('يجب توضيح سبب الاعتماد المباشر.'))
        self.request_id.action_direct_approve(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
