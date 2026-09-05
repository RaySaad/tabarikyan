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
    # ondelete='restrict' صراحة: إعادة تعريف الحقل هنا (لجعله
    # اختيارياً) كانت تُسقط ondelete='restrict' المفروضة في
    # bank_settlement_mixin.employee_id - وهي هناك تحديداً بسبب فقدان
    # بيانات فعلي سابق (حذف موظف كان يُفرغ الحقل بصمت على سجل نشط).
    # الحارس البايثوني في hr_employee.unlink يمنع الحالة عملياً، لكن هذا
    # هو خط الحماية الأخير على مستوى قاعدة البيانات.
    employee_id = fields.Many2one(
        'hr.employee', string='اسم الموظف', required=False, tracking=True,
        ondelete='restrict',
    )
    # يُستخدم فقط لتقييد قائمة السيارات أدناه بسيارات الموظف المختار -
    # غير مخزَّن، حقل مساعد للعرض فقط.
    employee_partner_id = fields.Many2one(
        'res.partner', compute='_compute_employee_partner_id',
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='السيارة', tracking=True,
        help='السيارة المرتبطة بهذا التحويل (مثال: مصروف وقود لسيارة '
             'محددة) - تُقيَّد القائمة تلقائياً بسيارات الموظف المختار '
             'أعلاه (سائقها الحالي أو المستقبلي)، ويمكن تركها فارغة إن '
             'كان التحويل عاماً غير مرتبط بسيارة بعينها.',
    )

    @api.depends('employee_id')
    def _compute_employee_partner_id(self):
        for rec in self:
            rec.employee_partner_id = rec.employee_id._get_personal_partner() if rec.employee_id else False

    @api.onchange('employee_id')
    def _onchange_employee_id_vehicle(self):
        """طلب صريح: اختيار الموظف يجب أن يربط سيارته تلقائياً (سائقها
        الحالي أو المستقبلي)، وليس فقط تقييد قائمة الاختيار وترك المستخدم
        يختارها يدوياً - كانت القائمة تُقيَّد صحيحاً بالفعل (domain حقل
        vehicle_id) لكن بلا أي تعبئة تلقائية، فيضطر المستخدم لاختيار نفس
        السيارة الوحيدة المتاحة يدوياً في كل مرة رغم معرفتها سلفاً.
        يستبدل أي سيارة سابقة (تخص موظفاً آخر على الأرجح إن تغيّر
        الموظف) - يطابق نفس منطق تقييد القائمة تماماً."""
        if not self.employee_id:
            self.vehicle_id = False
            return
        partner = self.employee_id._get_personal_partner()
        vehicle = self.env['fleet.vehicle'].search([
            '|', ('driver_id', '=', partner.id), ('future_driver_id', '=', partner.id),
        ], limit=1) if partner else self.env['fleet.vehicle']
        self.vehicle_id = vehicle

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
        return 'bank.settlement.vehicle.transfer'

    def _get_locked_fields_after_approval(self):
        return super()._get_locked_fields_after_approval() + [
            'transfer_type_id', 'vehicle_id',
        ]

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
                # يتجاوز قفل "لا تعديل بعد الاعتماد" عمداً - هجرة بيانات
                # قديمة، وليست تعديلاً حقيقياً لقيمة مختلفة.
                self.browse(rec_id).with_context(
                    bank_settlement_skip_approval_lock=True,
                ).transfer_type_id = new_record.id
