# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementGovernmentFee(models.Model):
    """الرسوم الحكومية — كود Gov/Fee/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.government.fee'
    _description = 'رسوم حكومية'
    _inherit = ['bank.settlement.mixin']

    # TODO: تحويلها لاحقاً إلى Many2one على نموذج "الجهات الحكومية" مخصص
    # بدلاً من Selection إذا كانت القائمة طويلة/قابلة للتوسع من المستخدم
    government_entity = fields.Selection(
        selection=[
            ('mol_resident', 'وزارة الداخلية ( مقيم )'),
            ('hrsd_expat', 'وزارة التنمية و الموارد البشرية ( قوى & أجير )'),
        ],
        string='الجهة الحكومية', required=True, tracking=True,
    )
    fee_type = fields.Selection(
        selection=[
            ('office_fee', 'رسوم مكتب العمل'),
            ('passport_fee', 'رسوم الجوازات'),
            ('sponsorship_transfer', 'رسوم نقل كفالة'),
        ],
        string='نوع الرسوم', required=True, tracking=True,
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
