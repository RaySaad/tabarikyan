# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BankSettlementGovernmentFee(models.Model):
    """الرسوم الحكومية — كود Gov/Fee/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.government.fee'
    _description = 'رسوم حكومية'
    _inherit = ['bank.settlement.mixin']

    partner_id = fields.Many2one(
        'res.partner', string='الشريك', tracking=True,
        help='الشريك الذي يُسجَّل على القيد المحاسبي لهذه الرسوم - '
             'يُشتق تلقائياً من الموظف المختار، أو يُضبط مبكراً (جهة '
             'اتصال المرشّح) عند إنشاء السجل تلقائياً من طلب توظيف قبل '
             'وجود سجل موظف رسمي بعد. يمكن تعديله يدوياً عند الحاجة.',
    )

    government_entity_id = fields.Many2one(
        'bank.settlement.government.entity', string='الجهة الحكومية',
        required=True, tracking=True,
    )
    fee_type_id = fields.Many2one(
        'bank.settlement.government.fee.type', string='نوع الرسوم',
        required=True, tracking=True,
    )
    recruitment_request_id = fields.Many2one(
        'recruitment.request', string='طلب التوظيف المرتبط',
        readonly=True, copy=False,
        help='إن أُنشئ هذا السجل تلقائياً من طلب توظيف (مرحلة نقل الكفالة) '
             'قبل وجود سجل الموظف الرسمي، يُربَط هنا - ويُكمَل حقل '
             '"اسم الموظف" أعلاه تلقائياً بمجرد إنشاء ذلك السجل لاحقاً.',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'مسددة'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.government.fee'

    @api.onchange('employee_id')
    def _onchange_employee_id_partner(self):
        if self.employee_id:
            self.partner_id = self.employee_id._get_personal_partner()

    def _get_settlement_partner_id(self):
        return self.partner_id.id if self.partner_id else super()._get_settlement_partner_id()

    def _get_locked_fields_after_approval(self):
        return super()._get_locked_fields_after_approval() + [
            'government_entity_id', 'fee_type_id', 'partner_id',
        ]

    _GOVERNMENT_ENTITY_MIGRATION_MAP = {
        'mol_resident': 'bank_settlement.government_entity_mol_resident',
        'hrsd_expat': 'bank_settlement.government_entity_hrsd_expat',
    }
    _FEE_TYPE_MIGRATION_MAP = {
        'office_fee': 'bank_settlement.government_fee_type_office_fee',
        'passport_fee': 'bank_settlement.government_fee_type_passport_fee',
        'sponsorship_transfer': 'bank_settlement.government_fee_type_sponsorship_transfer',
    }

    @api.model
    def _migrate_selection_fields_to_many2one(self):
        """يهاجر القيم القديمة (كانت Selection نصي) لحقلي "الجهة الحكومية"
        و"نوع الرسوم" إلى الحقلين الجديدين القابلين للتعديل من المستخدم
        (Many2one). العمودان القديمان لا يزالان موجودين فعلياً في قاعدة
        البيانات - أودو لا يحذف أعمدة الحقول المحذوفة تلقائياً - فنقرأهما
        مباشرة عبر SQL خام لأن النموذج نفسه لم يعد يعرّفهما. تعمل هذه
        الدالة بأمان حتى لو استُدعيت أكثر من مرة (لا تُعيد كتابة سجل
        مُهاجَر بالفعل)."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'bank_settlement_government_fee'
            AND column_name IN ('government_entity', 'fee_type')
        """)
        existing_columns = {row[0] for row in self.env.cr.fetchall()}

        if 'government_entity' in existing_columns:
            self.env.cr.execute("""
                SELECT id, government_entity FROM bank_settlement_government_fee
                WHERE government_entity_id IS NULL AND government_entity IS NOT NULL
            """)
            for rec_id, old_value in self.env.cr.fetchall():
                xmlid = self._GOVERNMENT_ENTITY_MIGRATION_MAP.get(old_value)
                new_record = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
                if new_record:
                    # يتجاوز قفل "لا تعديل بعد الاعتماد" عمداً - هجرة
                    # بيانات قديمة (قد تخص سجلاً مُعتمَداً/منفَّذاً فعلاً)،
                    # وليست تعديلاً حقيقياً لقيمة مختلفة.
                    self.browse(rec_id).with_context(
                        bank_settlement_skip_approval_lock=True,
                    ).government_entity_id = new_record.id

        if 'fee_type' in existing_columns:
            self.env.cr.execute("""
                SELECT id, fee_type FROM bank_settlement_government_fee
                WHERE fee_type_id IS NULL AND fee_type IS NOT NULL
            """)
            for rec_id, old_value in self.env.cr.fetchall():
                xmlid = self._FEE_TYPE_MIGRATION_MAP.get(old_value)
                new_record = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
                if new_record:
                    self.browse(rec_id).with_context(
                        bank_settlement_skip_approval_lock=True,
                    ).fee_type_id = new_record.id
