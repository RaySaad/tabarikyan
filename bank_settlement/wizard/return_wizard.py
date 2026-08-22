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
    # ملاحظة معمارية مهمة (بعد إصلاحين سابقين فشلا بالتتابع لنفس العَرَض
    # - قائمة فارغة أحياناً): توثيق get_views() في Odoo نفسه ("odoo/
    # addons/base/models/ir_ui_view.py") ينص صراحة أن نتيجتها (والتي
    # تستدعي fields_get() فتستدعي دالة selection= هذه) "لا يمكن أن
    # تعتمد إلا على أنواع العرض، صلاحيات الوصول، الخيارات، ولغة السياق -
    # ولا يمكن استخدام أي قيم سياق أخرى". وقد تحقّقنا فعلياً (عبر
    # odoo-bin shell) أن fields_get() تستدعي دالة selection= هذه دوماً
    # على سجل فارغ غير مرتبط بأي معرّف (env[self._name])، وليس على
    # المعالج الفعلي مهما كانت قيمه - أي أن:
    #   1) القراءة من self.res_model/self.res_id (المحاولة الأولى)
    #      تفشل دوماً هنا - self فارغ تماماً، لا قيمة له إطلاقاً.
    #   2) القراءة من self.env.context (الكود الأصلي) قد تنجح حين
    #      تُستدعى مباشرة بنفس السياق، لكنها تخالف عقد الإطار أعلاه -
    #      فتُعامَل النتيجة أحياناً كقابلة للتخزين المؤقت بمعزل عن قيمة
    #      السياق الفعلية، فتظهر القائمة فارغة أو من سجل سابق مختلف
    #      بشكل متقطع (هذا ما وقع فعلياً في الإنتاج مرتين).
    # الحل السليم: لا تعتمد قائمة الخيارات المعروضة على أي سجل/سياق
    # إطلاقاً - تُعرَض دوماً المجموعة الكاملة الثابتة لكل المراحل التي
    # قد تكون قابلة للإرجاع إليها عبر _get_returnable_stages() في أي من
    # النماذج الخمسة (راجع bank_settlement_mixin.py وadvance.py؛ حدِّث
    # هذه القائمة هنا يدوياً إن أُضيفت مرحلة جديدة هناك). التحقق الفعلي
    # من أن المرحلة المختارة صالحة لحالة *هذا* السجل تحديداً يبقى قائماً
    # ومُلزَماً من جهة الخادم في action_return_to_previous_stage() (طبقة
    # حماية مستقلة تماماً عن هذه القائمة) - فلا خطر أمني في عرض خيار قد
    # لا يصح لسجل بعينه؛ فقط سيُرفض عند التأكيد برسالة واضحة.
    target_state = fields.Selection(
        selection='_selection_target_state', string='الإرجاع إلى مرحلة',
        required=True,
        help='اختر المرحلة السابقة التي تريد إرجاع هذا السجل إليها '
             'للتصحيح - أي موافقة سابقة لهذه المرحلة تبقى سارية. قد تظهر '
             'هنا مراحل غير قابلة فعلياً للاختيار من حالة هذا السجل '
             'تحديداً - سيتم رفضها عند التأكيد إن لم تكن صالحة.',
    )
    reason = fields.Text(string='سبب الإرجاع للتصحيح', required=True)

    def _selection_target_state(self):
        return [
            ('under_review', 'تحت المراجعة'),
            ('pm_approved', 'وافق مسؤول المشروع'),
            ('waiting_approval', 'بانتظار الموافقة'),
        ]

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
