# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementResetWizard(models.TransientModel):
    """معالج إعادة سجل السداد البنكي لمسودة للتصحيح - يفرض تسجيل السبب،
    بنفس مبدأ bank.settlement.reject.wizard (res_model/res_id بدل
    Many2one مباشر، لأن الشاشات الخمس نماذج منفصلة)."""
    _name = 'bank.settlement.reset.wizard'
    _description = 'معالج إعادة سجل السداد البنكي لمسودة'

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الإعادة لمسودة', required=True)

    def action_confirm_reset(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب الإعادة لمسودة.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_reset_draft(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
