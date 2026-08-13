# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTypeMigration(TransactionCase):
    """يتحقق أن دالة الهجرة (_migrate_selection_fields_to_many2one) تنقل
    القيم القديمة (Selection نصي) فعلياً للحقول الجديدة (Many2one) - عبر
    محاكاة الوضع قبل الترقية (عمود قديم بقيمة نصية، حقل جديد فارغ)."""

    def test_government_fee_migration_maps_old_values(self):
        gov_fee = self.env['bank.settlement.government.fee'].create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': 500.0,
        })
        # نحاكي وجود العمودين القديمين (Selection) بقيمة مختلفة عن الحقلين
        # الجديدين الحاليين، ونُفرغ الحقلين الجديدين - تماماً كوضع سجل حقيقي
        # قبل الترقية لم يُهاجَر بعد.
        self.env.cr.execute("""
            ALTER TABLE bank_settlement_government_fee
            ADD COLUMN IF NOT EXISTS government_entity varchar,
            ADD COLUMN IF NOT EXISTS fee_type varchar
        """)
        self.env.cr.execute("""
            UPDATE bank_settlement_government_fee
            SET government_entity = 'hrsd_expat', fee_type = 'office_fee',
                government_entity_id = NULL, fee_type_id = NULL
            WHERE id = %s
        """, (gov_fee.id,))
        gov_fee.invalidate_recordset()
        self.assertFalse(gov_fee.government_entity_id)
        self.assertFalse(gov_fee.fee_type_id)

        self.env['bank.settlement.government.fee']._migrate_selection_fields_to_many2one()
        gov_fee.invalidate_recordset()

        self.assertEqual(
            gov_fee.government_entity_id,
            self.env.ref('bank_settlement.government_entity_hrsd_expat'),
        )
        self.assertEqual(
            gov_fee.fee_type_id,
            self.env.ref('bank_settlement.government_fee_type_office_fee'),
        )

        self.env.cr.execute("""
            ALTER TABLE bank_settlement_government_fee
            DROP COLUMN IF EXISTS government_entity,
            DROP COLUMN IF EXISTS fee_type
        """)

    def test_migration_is_idempotent_and_safe_without_old_columns(self):
        """الاستدعاء يجب ألا يفشل حتى لو لم يعد العمود القديم موجوداً
        إطلاقاً (الحالة الطبيعية بعد أول ترقية ناجحة)."""
        self.env['bank.settlement.government.fee']._migrate_selection_fields_to_many2one()
        self.env['bank.settlement.vehicle.transfer']._migrate_selection_fields_to_many2one()
        self.env['bank.settlement.medical.insurance']._migrate_selection_fields_to_many2one()
        self.env['bank.settlement.advance']._migrate_selection_fields_to_many2one()
