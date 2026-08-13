# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BankSettlementVehicleTransfer(models.Model):
    """تحويلات المركبات — كما ظهر في قائمة نوع التحويل الطويلة بالفيديو."""
    _name = 'bank.settlement.vehicle.transfer'
    _description = 'تحويل مركبة'
    _inherit = ['bank.settlement.mixin']

    transfer_type_id = fields.Many2one(
        'bank.settlement.vehicle.transfer.type', string='نوع التحويل',
        required=True, tracking=True,
    )

    # لاحظ في الفيديو أن هذا النموذج لا يحمل بالضرورة موظف/مندوب مرتبط
    # بشكل مباشر في كل الحالات (مثال: عهدة مسؤول حركة) — لذلك نجعله اختيارياً
    employee_id = fields.Many2one(
        'hr.employee', string='اسم الموظف', required=False, tracking=True,
    )
    # يُستخدم فقط لتقييد قائمة السيارات أدناه بسيارات الموظف المختار -
    # غير مخزَّن، حقل مساعد للعرض فقط.
    employee_partner_id = fields.Many2one(
        'res.partner', compute='_compute_employee_partner_id',
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='السيارة',
        help='السيارة المرتبطة بهذا التحويل (مثال: مصروف وقود لسيارة '
             'محددة) - تُقيَّد القائمة تلقائياً بسيارات الموظف المختار '
             'أعلاه (سائقها الحالي أو المستقبلي)، ويمكن تركها فارغة إن '
             'كان التحويل عاماً غير مرتبط بسيارة بعينها.',
    )

    @api.depends('employee_id')
    def _compute_employee_partner_id(self):
        for rec in self:
            rec.employee_partner_id = rec.employee_id._get_personal_partner() if rec.employee_id else False

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'تم التحويل'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.vehicle.transfer'

    _TRANSFER_TYPE_MIGRATION_MAP = {
        'sticker_purchase': 'bank_settlement.vehicle_transfer_type_sticker_purchase',
        'sticker_install': 'bank_settlement.vehicle_transfer_type_sticker_install',
        'vehicle_transfer': 'bank_settlement.vehicle_transfer_type_vehicle_transfer',
        'new_reg_public': 'bank_settlement.vehicle_transfer_type_new_reg_public',
        'new_reg_private': 'bank_settlement.vehicle_transfer_type_new_reg_private',
        'ownership_transfer_car': 'bank_settlement.vehicle_transfer_type_ownership_transfer_car',
        'ownership_transfer_bike': 'bank_settlement.vehicle_transfer_type_ownership_transfer_bike',
        'fuel_oil': 'bank_settlement.vehicle_transfer_type_fuel_oil',
        'bike_plate_issue': 'bank_settlement.vehicle_transfer_type_bike_plate_issue',
        'bike_form_issue': 'bank_settlement.vehicle_transfer_type_bike_form_issue',
        'form_issue_lost': 'bank_settlement.vehicle_transfer_type_form_issue_lost',
        'other': 'bank_settlement.vehicle_transfer_type_other',
        'plate_issue_lost': 'bank_settlement.vehicle_transfer_type_plate_issue_lost',
        'plate_change': 'bank_settlement.vehicle_transfer_type_plate_change',
        'public_transport_authority': 'bank_settlement.vehicle_transfer_type_public_transport_authority',
        'car_rental': 'bank_settlement.vehicle_transfer_type_car_rental',
        'driving_license': 'bank_settlement.vehicle_transfer_type_driving_license',
        'traffic_violation': 'bank_settlement.vehicle_transfer_type_traffic_violation',
        'movement_officer_custody': 'bank_settlement.vehicle_transfer_type_movement_officer_custody',
    }

    @api.model
    def _migrate_selection_fields_to_many2one(self):
        """يهاجر القيم القديمة (كانت Selection نصي) لحقل "نوع التحويل" -
        انظر نفس الشرح في government_fee._migrate_selection_fields_to_many2one."""
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'bank_settlement_vehicle_transfer'
            AND column_name = 'transfer_type'
        """)
        if not self.env.cr.fetchone():
            return
        self.env.cr.execute("""
            SELECT id, transfer_type FROM bank_settlement_vehicle_transfer
            WHERE transfer_type_id IS NULL AND transfer_type IS NOT NULL
        """)
        for rec_id, old_value in self.env.cr.fetchall():
            xmlid = self._TRANSFER_TYPE_MIGRATION_MAP.get(old_value)
            new_record = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
            if new_record:
                self.browse(rec_id).transfer_type_id = new_record.id
