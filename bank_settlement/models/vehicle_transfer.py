# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BankSettlementVehicleTransfer(models.Model):
    """تحويلات المركبات — كما ظهر في قائمة نوع التحويل الطويلة بالفيديو."""
    _name = 'bank.settlement.vehicle.transfer'
    _description = 'تحويل مركبة'
    _inherit = ['bank.settlement.mixin']

    # TODO: يفضّل نقلها لجدول "أنواع التحويل" مخصص (قابل للإضافة من الإعدادات)
    # بدلاً من Selection ثابت، لأن القائمة طويلة جداً وقابلة للتوسع.
    transfer_type = fields.Selection(
        selection=[
            ('sticker_purchase', 'شراء استيكرات'),
            ('sticker_install', 'تركيب استيكر'),
            ('vehicle_transfer', 'نقل مركبة'),
            ('new_reg_public', 'تسجيل سيارة جديدة نقل عام'),
            ('new_reg_private', 'تسجيل سيارة جديد نقل خصوصي'),
            ('ownership_transfer_car', 'نقل ملكية سيارة'),
            ('ownership_transfer_bike', 'نقل ملكية دباب'),
            ('fuel_oil', 'وقود وزيوت'),
            ('bike_plate_issue', 'أصدار لوحات دباب'),
            ('bike_form_issue', 'اصدار استمارة دباب'),
            ('form_issue_lost', 'اصدار استمارة بدل فاقد'),
            ('other', 'اخري'),
            ('plate_issue_lost', 'أصدار لوحة بدل فاقد'),
            ('plate_change', 'تغيير لوحات سيارة'),
            ('public_transport_authority', 'هيئة النقل العام'),
            ('car_rental', 'ايجار سيارة'),
            ('driving_license', 'رخصة قيادة'),
            ('traffic_violation', 'مخالفة مرور'),
            ('movement_officer_custody', 'عهدة مسؤول حركة'),
        ],
        string='نوع التحويل', required=True, tracking=True,
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
