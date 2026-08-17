# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementReturnWizard(models.TransientModel):
    """معالج "إرجاع للتصحيح" - يُرجع سجل السداد البنكي خطوة واحدة فقط
    للمرحلة السابقة مباشرة (مع الحفاظ على أي موافقة أسبق منها)، بعكس
    bank.settlement.reset.wizard الذي يعيده لمسودة بالكامل. يفرض تسجيل
    السبب، بنفس مبدأ reset_wizard.py/reject_wizard.py (res_model/res_id
    بدل Many2one مباشر، لأن الشاشات الخمس نماذج منفصلة)."""
    _name = 'bank.settlement.return.wizard'
    _description = 'معالج إرجاع سجل السداد البنكي للتصحيح'

    # نفس قائمة النماذج المغلقة المستخدمة في بقية معالجات السداد البنكي
    # - انظر الشرح في reject_wizard.py.
    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الإرجاع للتصحيح', required=True)

    def action_confirm_return(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب الإرجاع للتصحيح.')
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_return_to_previous_stage(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
