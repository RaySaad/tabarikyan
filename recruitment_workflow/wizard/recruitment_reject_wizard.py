# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class RecruitmentRejectWizard(models.TransientModel):
    _name = 'recruitment.reject.wizard'
    _description = 'مساعد رفض طلب التوظيف'

    request_id = fields.Many2one(
        'recruitment.request',
        string='الطلب',
        required=True,
    )
    reason = fields.Text(string='سبب الرفض', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason:
            raise UserError(_('يجب إدخال سبب الرفض.'))
        self.request_id.action_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
