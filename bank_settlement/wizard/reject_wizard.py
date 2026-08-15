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

    # قائمة مغلقة بالنماذج الخمسة الفعلية فقط - حماية دفاعية إضافية ضد
    # تمرير res_model لنموذج آخر عبر RPC مباشر (بما أن res_model/res_id
    # حقلان نصيان عاديان، بخلاف Many2one حقيقي يفرضه Odoo نفسه على مستوى
    # الحقل) - حتى لو كان الخطر العملي محدوداً (لا سودو هنا، صلاحيات
    # المستخدم الفعلية على أي نموذج آخر تبقى سارية).
    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الرفض', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب إدخال سبب الرفض.')
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
