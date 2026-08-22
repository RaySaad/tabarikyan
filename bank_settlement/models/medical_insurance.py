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

    def action_create_insurance_transfer(self):
        """ينشئ فاتورة مورد (Vendor Bill) فعلية على المورد المحدَّد، بدل
        القيد اليدوي العام المستخدم في بقية النماذج - لأن التأمين الطبي
        مرتبط بمورد حقيقي له فاتورة رسمية. ينهي دورة الحالة أيضاً (كانت
        سابقاً لا تصل لحالة "تم التحويل" لعدم تحديث state هنا إطلاقاً)."""
        self.ensure_one()
        # بلا هذا التحقق المبكر (قبل شرط "مؤكدة" أدناه)، نقرة مزدوجة أو
        # استدعاء مكرر (RPC) كان يفشل بخطأ "يجب تأكيد السجل أولاً" بدل
        # إرجاع نفس الفاتورة الموجودة فعلاً - لأن هذه الدالة نفسها تُغيّر
        # الحالة إلى "تم التحويل" فور نجاحها أول مرة، فيفشل شرط "مؤكدة"
        # عند أي استدعاء تالٍ رغم وجود الفاتورة أصلاً (ثغرة حقيقية
        # مكتشفة بالاختبار الفعلي - الاختبار الذي يُفترض أن يتحقق من
        # التكرار الآمن كان هو نفسه يفشل بخطأ مختلف تماماً عن المتوقَّع).
        if self.move_id:
            return self.move_id.id
        if self.state != 'confirmed':
            raise UserError('يجب تأكيد السجل أولاً قبل إنشاء تحويل التأمين.')
        self._check_group(
            'bank_settlement.group_bank_settlement_reviewer',
            'bank_settlement.group_bank_settlement_manager',
        )
        if not self.vendor_id:
            raise UserError('يجب تحديد المورد أولاً لإنشاء تحويل التأمين.')
        # sudo(): نفس منطق _create_settlement_move في المixin - لا يجوز أن
        # يشترط إنشاء الفاتورة عضوية محاسبية أصلية بـ Odoo؛ الصلاحية الفعلية
        # محكومة بالفعل عبر _check_group أعلاه.
        move = self.env['account.move'].sudo().create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor_id.id,
            # الشركة صراحة من شركة السجل نفسها - بدل تركها تُحسب من الشركة
            # النشطة لمن يضغط الزر (انظر نفس المنطق في _create_settlement_move).
            'company_id': self.company_id.id,
            # يُستخدم لحصر رؤية "مستخدم/محاسب" السداد البنكي على قيودهم فقط
            # عبر ir.rule - دون كشف بقية فواتير الشركة.
            'is_bank_settlement_move': True,
            'ref': self.name,
            'invoice_date': self.transfer_date or fields.Date.context_today(self),
            'invoice_line_ids': [(0, 0, {
                'name': self.name,
                'quantity': 1,
                'price_unit': self.total_amount,
                'analytic_distribution': (
                    {str(self.analytic_account_id.id): 100}
                    if self.analytic_account_id else False
                ),
            })],
        })
        self.move_id = move.id
        self.state = 'done'
        return self.move_id.id
