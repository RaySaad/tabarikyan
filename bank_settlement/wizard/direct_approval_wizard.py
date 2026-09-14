# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementDirectApprovalWizard(models.TransientModel):
    """معالج الاعتماد المباشر من الإدارة - يفرض تسجيل السبب، بنفس نمط
    معالجات الرفض والإرجاع (res_model/res_id لأن الشاشات الخمس نماذج
    منفصلة تشترك في مِكسِن تجريدي)."""
    _name = 'bank.settlement.direct.approval.wizard'
    _description = 'معالج الاعتماد المباشر لسجل السداد البنكي'

    # قائمة مغلقة - res_model حقل نصي يمكن تمريره عبر RPC.
    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الاعتماد المباشر', required=True)

    def action_confirm_direct_approval(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب الاعتماد المباشر.')
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        self.env[self.res_model].browse(self.res_id).action_direct_approve(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
