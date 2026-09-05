# -*- coding: utf-8 -*-
from odoo import models, fields

# أنواع طلب تغيير المركبة - معرَّفة مرة واحدة هنا وتُستورَد في بقية
# النماذج (الطلب، سبب التبديل، نوع المرفق) بدل تكرار نفس القائمة في كل
# ملف والوقوع في اختلافها لاحقاً عند إضافة نوع جديد.
VEHICLE_CHANGE_TYPES = [
    ('accident', 'حادث'),
    ('breakdown', 'عطل'),
    ('plate', 'لوحة'),
]

# نفس القائمة أعلاه زائد "الكل" - للسجلات الإعدادية (سبب/نوع مرفق) التي
# قد تنطبق على كل الأنواع بلا تخصيص.
VEHICLE_CHANGE_TYPES_WITH_ALL = VEHICLE_CHANGE_TYPES + [('all', 'كل الأنواع')]


class FleetVehicleChangeReason(models.Model):
    """سبب تبديل المركبة - قائمة قابلة للتعديل والإضافة من المستخدم نفسه
    (سير عمل التوظيف ← الإعدادات)، بدل نص ثابت بالكود لا يقدر أحد غير
    المطوّر توسيعه. كل سبب مرتبط بنوع الطلب الذي يظهر تحته (أو "كل
    الأنواع")، فتُفلتَر القائمة تلقائياً حسب النوع المختار في الطلب."""
    _name = 'fleet.vehicle.change.reason'
    _description = 'سبب تبديل المركبة'
    _order = 'sequence, name'

    name = fields.Char(string='السبب', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    request_type = fields.Selection(
        selection=VEHICLE_CHANGE_TYPES_WITH_ALL,
        string='نوع الطلب', default='all', required=True,
        help='نوع الطلب الذي يظهر تحته هذا السبب - أو "كل الأنواع" ليظهر دائماً.',
    )
    active = fields.Boolean(default=True)

    # _sql_constraints (الصيغة القديمة) لم تعد فعّالة في هذا الإصدار من
    # أودو - تُستخدَم models.Constraint بدلاً منها (نفس ما في
    # bank_settlement/models/advance_reason.py).
    _name_type_uniq = models.Constraint(
        'unique(name, request_type)',
        'يوجد سبب تبديل آخر بنفس الاسم لنفس نوع الطلب بالفعل.',
    )


class FleetVehicleChangeAttachmentType(models.Model):
    """نوع المرفق المطلوب في طلب تغيير المركبة - نفس مبدأ recruitment.
    attachment.type في طلبات التوظيف (قائمة قابلة للتعديل + علم "إجباري"
    يمنع إرسال الطلب قبل رفعه)، لكن مفلترة هنا حسب نوع الطلب: مرفقات
    الحادث (تقرير المسؤولية/التقديرات/الصور) لا تُطلَب في طلب "لوحة"،
    ومرفق فيديو العطل لا يُطلَب في طلب حادث."""
    _name = 'fleet.vehicle.change.attachment.type'
    _description = 'نوع مرفق طلب تغيير المركبة'
    _order = 'sequence, id'

    name = fields.Char(string='اسم المرفق', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    request_type = fields.Selection(
        selection=VEHICLE_CHANGE_TYPES_WITH_ALL,
        string='نوع الطلب', default='all', required=True,
        help='نوع الطلب الذي يُطلَب فيه هذا المرفق - أو "كل الأنواع" ليُطلَب دائماً.',
    )
    required = fields.Boolean(
        string='إجباري', default=True,
        help='إذا كان إجبارياً، لا يمكن إرسال الطلب للمراجعة قبل رفعه.',
    )
    description = fields.Text(string='ملاحظات', translate=True)
    active = fields.Boolean(default=True)
