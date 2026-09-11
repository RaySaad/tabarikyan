# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class BankSettlementMedicalInsurance(models.Model):
    """التأمين الطبي — مرتبط بمورد (Vendor) كما ظهر في الفيديو."""
    _name = 'bank.settlement.medical.insurance'
    _description = 'تأمين / فحص طبي'
    _inherit = ['bank.settlement.mixin']

    fee_type_id = fields.Many2one(
        'bank.settlement.medical.insurance.type', string='نوع الرسوم',
        required=True, tracking=True,
    )
    vendor_id = fields.Many2one(
        'res.partner', string='المورد', domain=[('supplier_rank', '>', 0)],
        tracking=True,
    )
    # tracking=True مهم تحديداً هنا - وجهة تحويل التأمين الفعلية، كانت
    # بلا أي تتبع (ثغرة تدقيق حقيقية على حقل يمثّل أين تذهب الأموال).
    company_iban = fields.Char(string='آيبان الشركة', tracking=True)

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'تم التحويل'),
            ('rejected', 'مرفوضة'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.medical.insurance'

    def _get_locked_fields_after_approval(self):
        # vendor_id (المورد) مستثنى عمداً هنا - طلب صريح: يبقى موجوداً
        # وقابلاً للتعديل من "مسودة" وحتى آخر مرحلة (وليس مقفولاً فور
        # مغادرة "مسودة" كباقي حقول الهوية) - انظر القيد الخاص به وحده
        # في write() أدناه (يُقفَل فقط عند اكتمال/انتهاء السجل).
        return super()._get_locked_fields_after_approval() + [
            'fee_type_id', 'company_iban',
        ]

    def write(self, vals):
        if 'vendor_id' in vals and not self.env.context.get('bank_settlement_skip_approval_lock'):
            for rec in self:
                if rec.state in ('done', 'rejected', 'cancel'):
                    raise UserError(
                        'لا يمكن تعديل "المورد" بعد اكتمال السجل (تم '
                        'التحويل/رُفض/أُلغي).'
                    )
        return super().write(vals)

    _FEE_TYPE_MIGRATION_MAP = {
        'medical_insurance': 'bank_settlement.medical_insurance_type_medical_insurance',
        'medical_checkup': 'bank_settlement.medical_insurance_type_medical_checkup',
    }

    @api.model
    def _migrate_selection_fields_to_many2one(self):
        """يهاجر القيم القديمة (كانت Selection نصي) لحقل "نوع الرسوم" -
        انظر نفس الشرح في government_fee._migrate_selection_fields_to_many2one."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'bank_settlement_medical_insurance'
            AND column_name = 'fee_type'
        """)
        if not self.env.cr.fetchone():
            return
        self.env.cr.execute("""
            SELECT id, fee_type FROM bank_settlement_medical_insurance
            WHERE fee_type_id IS NULL AND fee_type IS NOT NULL
        """)
        for rec_id, old_value in self.env.cr.fetchall():
            xmlid = self._FEE_TYPE_MIGRATION_MAP.get(old_value)
            new_record = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
            if new_record:
                # يتجاوز قفل "لا تعديل بعد الاعتماد" عمداً - هجرة بيانات
                # قديمة، وليست تعديلاً حقيقياً لقيمة مختلفة.
                self.browse(rec_id).with_context(
                    bank_settlement_skip_approval_lock=True,
                ).fee_type_id = new_record.id

    def _uses_vendor_bill(self):
        # التأمين الطبي دائماً فاتورة مورد - مرتبط بمورد حقيقي يُصدر
        # فاتورة رسمية، لا صرف نقدي مباشر.
        return True

    def _get_settlement_vendor(self):
        return self.vendor_id

    def action_create_insurance_transfer(self):
        """ينشئ فاتورة المورد ويرحّلها وينهي دورة الحالة.

        صارت غلافاً رفيعاً حول action_done المشتركة بدل تنفيذ مستقل -
        وبذلك تسري على التأمين الطبي كل آليات السداد الأخرى بلا تكرار:
        الترحيل الفوري، و"إرجاع للتصحيح" (يعيد الفاتورة مسودة ثم
        يحدّثها بالقيم الجديدة ويرحّلها)، و"إلغاء التنفيذ وتصحيح".

        كان التنفيذ المستقل السابق يترك الفاتورة *مسودة* أبداً، ويتجاهل
        "الحساب المرتبط" و"دفتر اليومية" تماماً، ويخرج مبكراً متى وُجد
        move_id - فبعد إرجاع السجل للتصحيح كان يعلَق نهائياً: الفاتورة
        مسودة بقيمها القديمة، والضغط على الزر لا يحدّثها ولا يُعيد
        الحالة لـ"تم التحويل"."""
        self.ensure_one()
        # استدعاء مكرر (نقرة مزدوجة/RPC) على سجل مكتمل فعلاً: يُرجع نفس
        # الفاتورة بدل الفشل بخطأ "يجب تأكيد السجل أولاً" - لأن الدالة
        # نفسها تنقل الحالة إلى "تم التحويل" فور نجاحها أول مرة.
        if self.move_id and self.state == 'done':
            return self.move_id.id
        if not self.vendor_id:
            raise UserError('يجب تحديد المورد أولاً لإنشاء تحويل التأمين.')
        self.action_done()
        return self.move_id.id
