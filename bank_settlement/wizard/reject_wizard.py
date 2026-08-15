# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementRejectWizard(models.TransientModel):
    """معالج رفض سجل السداد البنكي - يفرض تسجيل السبب، ويعمل عبر أي من
    الشاشات الخمس (res_model/res_id بدل Many2one مباشر لنموذج محدد،
    لأن الشاشات الخمس نماذج منفصلة تشترك فقط في bank.settlement.mixin
    التجريدي بلا جدول خاص به يمكن الإشارة إليه مباشرة)."""
    _name = 'bank.settlement.reject.wizard'
    _description = 'معالج رفض سجل السداد البنكي'

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الرفض', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب إدخال سبب الرفض.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
