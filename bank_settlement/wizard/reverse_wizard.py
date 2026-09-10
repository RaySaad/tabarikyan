# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementReverseWizard(models.TransientModel):
    """معالج "إلغاء التنفيذ وتصحيح" - يفرض تسجيل السبب، ويعمل عبر أي من
    الشاشات الخمس (res_model/res_id بدل Many2one مباشر، بنفس سبب معالجَي
    الرفض والإرجاع: الشاشات الخمس نماذج منفصلة تشترك في مِكسِن تجريدي
    بلا جدول يمكن الإشارة إليه)."""
    _name = 'bank.settlement.reverse.wizard'
    _description = 'معالج إلغاء تنفيذ سجل السداد البنكي وتصحيحه'

    # قائمة مغلقة بالنماذج الخمسة - حماية دفاعية ضد تمرير res_model
    # لنموذج آخر عبر RPC مباشر (res_model حقل نصي عادي لا Many2one).
    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب إلغاء التنفيذ', required=True)

    def action_confirm_reverse(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب إلغاء التنفيذ.')
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_reverse_and_correct(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
