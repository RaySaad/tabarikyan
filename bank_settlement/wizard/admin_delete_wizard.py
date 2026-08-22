# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementAdminDeleteWizard(models.TransientModel):
    """معالج "الحذف النهائي الإداري" - أداة استثنائية (مُغلَقة افتراضياً،
    انظر bank_settlement_mixin._is_admin_delete_enabled) لتنظيف بيانات
    خاطئة/تجريبية وصلت لأي مرحلة، مع عكس القيد المحاسبي المرتبط بشكل
    سليم إن كان مرحّلاً. يفرض كتابة عبارة تأكيد صريحة بالإضافة للسبب،
    فوق الحماية العادية (سبب + صلاحية مدير) المستخدمة في باقي المعالجات
    - نظراً لخطورة هذا الإجراء تحديداً وعدم إمكانية التراجع عنه."""
    _name = 'bank.settlement.admin.delete.wizard'
    _description = 'معالج الحذف النهائي الإداري - سداد بنكي'

    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )
    _CONFIRMATION_TEXT = 'حذف نهائي'

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    reason = fields.Text(string='سبب الحذف النهائي', required=True)
    confirmation_text = fields.Char(
        string='اكتب "حذف نهائي" للتأكيد', required=True,
        help='طبقة تأكيد إضافية - هذا الإجراء لا يمكن التراجع عنه.',
    )

    def action_confirm_delete(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب الحذف النهائي.')
        if (self.confirmation_text or '').strip() != self._CONFIRMATION_TEXT:
            raise UserError('يجب كتابة "%s" بالضبط للتأكيد.' % self._CONFIRMATION_TEXT)
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_admin_force_delete(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
