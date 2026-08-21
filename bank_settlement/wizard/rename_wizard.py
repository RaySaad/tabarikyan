# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementRenameWizard(models.TransientModel):
    """معالج "تعديل الكود الإداري" - أداة استثنائية (مُغلَقة افتراضياً،
    تستخدم نفس مفتاح bank_settlement_mixin._is_admin_delete_enabled الذي
    يفعّل الحذف النهائي الإداري وإعادة ضبط الترقيم) لتصحيح فجوة/ترتيب في
    أكواد سجلات موجودة فعلاً - وليس جزءاً من سير العمل المعتاد (الكود
    مقفول عمداً بعد الإنشاء للحفاظ على سجل تدقيق ثابت). يفرض كتابة عبارة
    تأكيد صريحة بالإضافة للسبب، بنفس مستوى حماية معالج الحذف النهائي."""
    _name = 'bank.settlement.rename.wizard'
    _description = 'معالج تعديل الكود الإداري - سداد بنكي'

    _VALID_RES_MODELS = (
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.medical.insurance',
        'bank.settlement.representative',
    )
    _CONFIRMATION_TEXT = 'تعديل الكود'

    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    old_code = fields.Char(string='الكود الحالي', readonly=True)
    new_code = fields.Char(string='الكود الجديد', required=True)
    reason = fields.Text(string='سبب التعديل', required=True)
    confirmation_text = fields.Char(
        string='اكتب "تعديل الكود" للتأكيد', required=True,
        help='طبقة تأكيد إضافية - تعديل الكود بعد اعتماده/تنفيذه فعلياً '
             'يجب أن يكون استثناءً واعياً، وليس تعديلاً عابراً.',
    )

    def action_confirm_rename(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب تعديل الكود.')
        if (self.confirmation_text or '').strip() != self._CONFIRMATION_TEXT:
            raise UserError('يجب كتابة "%s" بالضبط للتأكيد.' % self._CONFIRMATION_TEXT)
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_admin_rename(new_code=self.new_code, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
