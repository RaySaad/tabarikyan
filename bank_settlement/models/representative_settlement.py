# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementRepresentative(models.Model):
    """تصفيات المناديب — كود Del/sett/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.representative'
    _description = 'تصفية مندوب'
    _inherit = ['bank.settlement.mixin']

    date = fields.Date(string='التاريخ', default=fields.Date.context_today, tracking=True)
    # tracking=True مهم تحديداً هنا - وجهة تصفية المندوب الفعلية، كانت
    # بلا أي تتبع (ثغرة تدقيق حقيقية على حقل يمثّل أين تذهب الأموال).
    iban = fields.Char(string='الأيبان', tracking=True)

    # "ID رقم" في الفيديو — تعريف المندوب داخل تطبيق التوصيل (كيتا/جاهز/هنقرستيشن)
    platform_employee_id = fields.Char(string='ID رقم (داخل التطبيق)', tracking=True)

    settlement_amount = fields.Monetary(
        string='مبلغ التصفية', related='amount', readonly=False,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'مسددة'),
            ('rejected', 'مرفوضة'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.representative'

    def _get_locked_fields_after_approval(self):
        # settlement_amount اسم بديل لحقل amount نفسه (related) - يُقفل
        # هو أيضاً بعد الاعتماد، تماماً كما لو كُتب على amount مباشرة.
        # iban/platform_employee_id/date: وجهة الدفع الفعلية، هوية المندوب
        # داخل تطبيق المنصة، وتاريخ التصفية - كانت بلا أي قفل إطلاقاً
        # سابقاً (ثغرة حقيقية).
        return super()._get_locked_fields_after_approval() + [
            'settlement_amount', 'iban', 'platform_employee_id', 'date',
        ]
