# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class BankSettlementReturnWizard(models.TransientModel):
    """معالج "إرجاع للتصحيح" - يُرجع سجل السداد البنكي إلى مرحلة سابقة
    يختارها المستخدم صراحة (مع الحفاظ على أي موافقة أسبق من تلك المرحلة)
    - بنفس مبدأ اختيار المرحلة المستهدفة في recruitment.return.wizard.
    يفرض تسجيل السبب، بنفس مبدأ reject_wizard.py (res_model/res_id بدل
    Many2one مباشر، لأن الشاشات الخمس نماذج منفصلة)."""
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
    # القائمة تُبنى ديناميكياً من _get_returnable_stages() الخاصة
    # بالسجل المستهدف نفسه (عبر السياق res_model/res_id الممرَّر عند فتح
    # المعالج) - لا يمكن أن تكون Selection ثابتة لأن كل نموذج (بل وكل
    # حالة حالية) له مراحل سابقة مختلفة (انظر bank_settlement_mixin.py
    # وadvance.py).
    target_state = fields.Selection(
        selection='_selection_target_state', string='الإرجاع إلى مرحلة',
        required=True,
        help='اختر المرحلة السابقة التي تريد إرجاع هذا السجل إليها '
             'للتصحيح - أي موافقة سابقة لهذه المرحلة تبقى سارية.',
    )
    reason = fields.Text(string='سبب الإرجاع للتصحيح', required=True)

    def _selection_target_state(self):
        # ثغرة حقيقية اكتُشفت من الاستخدام الفعلي: القراءة من self.env.
        # context هنا (بدل حقلي res_model/res_id المخزَّنين فعلياً على
        # المعالج نفسه) كانت تفشل بصمت وتُرجع قائمة فارغة ("لا توجد
        # نتائج") في بعض الحالات - سياق فتح الإجراء الأصلي (default_
        # res_model/default_res_id) لا يبقى مضموناً متاحاً عبر self.env.
        # context عند كل إعادة حساب لاحقة لقائمة هذا الحقل (مثلاً بعد أي
        # onchange/إعادة رسم للشاشة)، بعكس قيمتي حقلي res_model/res_id
        # أنفسهما - تُملأ مرة واحدة فقط من نفس السياق عند إنشاء السجل
        # (افتراضي default_get قياسي)، لكنها تبقى ثابتة كقيمة حقل عادي
        # بعدها بغض النظر عن أي تغيّر لاحق في السياق المحيط.
        res_model = self.res_model
        res_id = self.res_id
        if not res_model or not res_id or res_model not in self._VALID_RES_MODELS:
            return []
        record = self.env[res_model].browse(res_id)
        if not record.exists():
            return []
        return record._get_returnable_stages()

    def action_confirm_return(self):
        self.ensure_one()
        if not self.reason:
            raise UserError('يجب توضيح سبب الإرجاع للتصحيح.')
        if not self.target_state:
            raise UserError('يجب اختيار المرحلة المراد الإرجاع إليها.')
        if self.res_model not in self._VALID_RES_MODELS:
            raise UserError('نموذج غير صالح.')
        record = self.env[self.res_model].browse(self.res_id)
        record.action_return_to_previous_stage(
            target_state=self.target_state, reason=self.reason,
        )
        return {'type': 'ir.actions.act_window_close'}
