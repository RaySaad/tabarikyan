# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class RecruitmentRequest(models.Model):
    """يربط طلب التوظيف تلقائياً بسجل "الرسوم الحكومية" في السداد البنكي
    فور تسجيل المبلغ الإجمالي لرسوم نقل الكفالة - بدل بقاء هذا السجل
    منفصلاً بلا علاقة بطلب التوظيف، أو الاضطرار لإنشائه يدوياً لاحقاً.

    هذا الملف موجود في bank_settlement وليس recruitment_workflow عمداً:
    bank_settlement يعتمد على recruitment_workflow (وليس العكس)، فهو
    الجهة الوحيدة القادرة تقنياً على التوسّع على نموذج recruitment.request.
    """
    _inherit = 'recruitment.request'

    bank_settlement_gov_fee_id = fields.Many2one(
        'bank.settlement.government.fee', string='سجل الرسوم الحكومية',
        readonly=True, copy=False,
    )
    bank_settlement_gov_fee_state = fields.Selection(
        related='bank_settlement_gov_fee_id.state', string='حالة سداد الرسوم الحكومية',
        readonly=True,
    )

    def action_register_gov_fee(self):
        result = super().action_register_gov_fee()
        for rec in self:
            if not rec.bank_settlement_gov_fee_id:
                rec.bank_settlement_gov_fee_id = rec._create_bank_settlement_gov_fee_record()
        return result

    def _validate_stage_exit(self, current_stage):
        """يضيف شرط مرحلة "تم السداد" الفعلي عندكم: تأكيد سداد إجمالي
        الرسوم الحكومية للمنصة/الجهة الحكومية (سجل "الرسوم الحكومية" في
        السداد البنكي بحالة "منفّذة") - بدل شرط فاتورة المورّد الخارجي
        غير المستخدم أصلاً (recruitment_workflow الأساسي يتجاوزه الآن إن
        كان fee_amount صفراً)."""
        super()._validate_stage_exit(current_stage)
        self.ensure_one()
        if current_stage.code == 'paid' and self.gov_fee_amount > 0:
            if not self.bank_settlement_gov_fee_id:
                raise UserError(
                    'لا يمكن الانتقال للمرحلة التالية. يجب تسجيل الرسوم '
                    'الحكومية أولاً (زر "تسجيل الرسوم الحكومية").'
                )
            if self.bank_settlement_gov_fee_id.state != 'done':
                raise UserError(
                    'لا يمكن الانتقال للمرحلة التالية. لم يُؤكَّد سداد '
                    'الرسوم الحكومية للمنصة/الجهة الحكومية بعد من السداد '
                    'البنكي (%s) - يجب إتمامه من هناك أولاً.'
                    % self.bank_settlement_gov_fee_id.name
                )

    def _create_bank_settlement_gov_fee_record(self):
        """ينشئ سجل "رسوم حكومية" في السداد البنكي فوراً، معبَّأً بنفس
        المبلغ الإجمالي المسجَّل على طلب التوظيف - بدون موظف رسمي بعد (لا
        سجل hr.employee وقت نقل الكفالة)، لكن مرتبطاً فوراً بجهة اتصال
        المرشّح الخفيفة (candidate_partner_id) كشريك على القيد المحاسبي -
        بدل بقاء القيد بلا شريك حتى إنشاء سجل الموظف الرسمي المتأخر لآخر
        مرحلة. يُكمَل حقل الموظف نفسه لاحقاً تلقائياً في _create_employee()
        أدناه.

        ملاحظة: "الجهة الحكومية" تُضبط افتراضياً بـ"وزارة الداخلية (مقيم)"
        - عدّلها يدوياً من سجل الرسوم نفسه في السداد البنكي إن كانت جهة
        نقل الكفالة الفعلية مختلفة (مثال: قوى/مساند).
        """
        self.ensure_one()
        partner = self._get_or_create_candidate_partner()
        return self.env['bank.settlement.government.fee'].sudo().create({
            'government_entity_id': self.env.ref(
                'bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref(
                'bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': self.gov_fee_amount,
            'recruitment_request_id': self.id,
            'partner_id': partner.id,
            # الشركة صراحة من طلب التوظيف نفسه (مُشتقة أصلاً من المشروع/
            # المنصة المختارة) - بدل تركها تُحسب من الشركة النشطة لمن
            # يضغط زر "تسجيل الرسوم الحكومية"، والتي قد تختلف عن فرع
            # المشروع الفعلي.
            'company_id': self.company_id.id,
            'project_id': self.project_id.id,
            'transfer_date': fields.Date.context_today(self),
        }).id

    def _create_employee(self):
        employee = super()._create_employee()
        self.ensure_one()
        if self.bank_settlement_gov_fee_id and not self.bank_settlement_gov_fee_id.employee_id:
            self.bank_settlement_gov_fee_id.write({
                'employee_id': employee.id,
                'partner_id': employee._get_personal_partner().id,
            })
        return employee
