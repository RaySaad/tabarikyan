# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class RecruitmentRequest(models.Model):
    """يربط طلب التوظيف تلقائياً بسجلات السداد البنكي المرتبطة برسوم نقل
    الكفالة الحكومية: سجل "الرسوم الحكومية" (المبلغ الإجمالي المسدَّد
    للمنصة/الجهة الحكومية)، وإن اختير للموظف سداد "سلفة"، سجل "سلفة"
    مستقل يُخصم لاحقاً من راتبه - بدل بقاء هذه السجلات منفصلة بلا علاقة
    بطلب التوظيف، أو الاضطرار لإنشائها يدوياً لاحقاً.

    هذا الملف موجود في bank_settlement وليس recruitment_workflow عمداً:
    bank_settlement يعتمد على recruitment_workflow (وليس العكس)، فهو
    الجهة الوحيدة القادرة تقنياً على التوسّع على نموذج recruitment.request.
    """
    _inherit = 'recruitment.request'

    bank_settlement_gov_fee_id = fields.Many2one(
        'bank.settlement.government.fee', string='سجل الرسوم الحكومية',
        readonly=True, copy=False,
    )
    bank_settlement_advance_id = fields.Many2one(
        'bank.settlement.advance', string='سجل سلفة الموظف',
        readonly=True, copy=False,
    )

    def action_create_gov_fee_employee_invoice(self):
        result = super().action_create_gov_fee_employee_invoice()
        for rec in self:
            if not rec.bank_settlement_gov_fee_id:
                rec.bank_settlement_gov_fee_id = rec._create_bank_settlement_gov_fee_record()
        return result

    def _settle_gov_fee_employee_share(self):
        """تسوية "سلفة" فقط مُنفَّذة هنا: تُنشئ سجل سلفة في السداد البنكي
        بدل الفاتورة - تُخصَم لاحقاً من راتب الموظف عبر دورة موافقة/صرف
        السلف المستقلة هناك. تسوية "نقداً" تبقى من مسؤولية recruitment_workflow
        الأساسي (فاتورة عميل)."""
        if self.gov_fee_employee_amount > 0 and self.gov_fee_employee_payment_method == 'advance' \
                and not self.bank_settlement_advance_id:
            self.bank_settlement_advance_id = self._create_bank_settlement_advance_record()
            return
        super()._settle_gov_fee_employee_share()

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
        المبالغ والفاتورة الصادرة من طلب التوظيف - بدون موظف بعد (لا
        سجل hr.employee رسمي وقت نقل الكفالة)؛ يُكمَل لاحقاً تلقائياً في
        _create_employee() أدناه.

        ملاحظة: "الجهة الحكومية" تُضبط افتراضياً بـ"وزارة الداخلية (مقيم)"
        - عدّلها يدوياً من سجل الرسوم نفسه في السداد البنكي إن كانت جهة
        نقل الكفالة الفعلية مختلفة (مثال: قوى/مساند).
        """
        self.ensure_one()
        return self.env['bank.settlement.government.fee'].sudo().create({
            'government_entity': 'mol_resident',
            'fee_type': 'sponsorship_transfer',
            'amount': self.gov_fee_amount,
            'employee_amount': self.gov_fee_employee_amount,
            'employee_move_id': self.gov_fee_employee_move_id.id,
            'recruitment_request_id': self.id,
            'project_id': self.project_id.id,
            'transfer_date': fields.Date.context_today(self),
        }).id

    def _create_bank_settlement_advance_record(self):
        """سلفة على الموظف بقيمة حصته من الرسوم الحكومية - تُخصم لاحقاً
        من راتبه عبر شاشة السلف في السداد البنكي (دورة موافقة/صرف مستقلة
        عن دورة الرسوم الحكومية نفسها)."""
        self.ensure_one()
        return self.env['bank.settlement.advance'].sudo().create({
            'advance_reason': 'salary_advance',
            'amount': self.gov_fee_employee_amount,
            'recruitment_request_id': self.id,
            'project_id': self.project_id.id,
            'transfer_date': fields.Date.context_today(self),
        }).id

    def _create_employee(self):
        employee = super()._create_employee()
        self.ensure_one()
        if self.bank_settlement_gov_fee_id and not self.bank_settlement_gov_fee_id.employee_id:
            self.bank_settlement_gov_fee_id.employee_id = employee.id
        if self.bank_settlement_advance_id and not self.bank_settlement_advance_id.employee_id:
            self.bank_settlement_advance_id.employee_id = employee.id
        return employee

    def action_view_bank_settlement_gov_fee(self):
        self.ensure_one()
        return {
            'name': 'الرسوم الحكومية',
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.government.fee',
            'res_id': self.bank_settlement_gov_fee_id.id,
            'view_mode': 'form',
        }

    def action_view_bank_settlement_advance(self):
        self.ensure_one()
        return {
            'name': 'سلفة الموظف',
            'type': 'ir.actions.act_window',
            'res_model': 'bank.settlement.advance',
            'res_id': self.bank_settlement_advance_id.id,
            'view_mode': 'form',
        }
