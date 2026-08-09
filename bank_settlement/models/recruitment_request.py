# -*- coding: utf-8 -*-
from odoo import fields, models


class RecruitmentRequest(models.Model):
    """يربط طلب التوظيف تلقائياً بسجل "الرسوم الحكومية" في السداد البنكي
    فور إصدار فاتورة حصة الموظف من رسوم نقل الكفالة - بدل بقائهما سجلين
    منفصلين بلا علاقة بينهما، أو الاضطرار لإنشاء الثاني يدوياً لاحقاً.

    هذا الملف موجود في bank_settlement وليس recruitment_workflow عمداً:
    bank_settlement يعتمد على recruitment_workflow (وليس العكس)، فهو
    الجهة الوحيدة القادرة تقنياً على التوسّع على نموذج recruitment.request.
    """
    _inherit = 'recruitment.request'

    bank_settlement_gov_fee_id = fields.Many2one(
        'bank.settlement.government.fee', string='سجل الرسوم الحكومية',
        readonly=True, copy=False,
    )

    def action_create_gov_fee_employee_invoice(self):
        result = super().action_create_gov_fee_employee_invoice()
        for rec in self:
            if not rec.bank_settlement_gov_fee_id:
                rec.bank_settlement_gov_fee_id = rec._create_bank_settlement_gov_fee_record()
        return result

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

    def _create_employee(self):
        employee = super()._create_employee()
        self.ensure_one()
        if self.bank_settlement_gov_fee_id and not self.bank_settlement_gov_fee_id.employee_id:
            self.bank_settlement_gov_fee_id.employee_id = employee.id
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
