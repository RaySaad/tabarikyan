# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementGovernmentEntity(models.Model):
    """الجهة الحكومية (وزارة الداخلية، قوى...) - قائمة قابلة للتعديل
    والإضافة من المستخدم نفسه (السداد البنكي ← الإعدادات)، بدل قائمة
    ثابتة بالكود لا يقدر أحد غير المطوّر توسيعها."""
    _name = 'bank.settlement.government.entity'
    _description = 'الجهة الحكومية'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)
    # بعض الجهات تُسدَّد عبر مورد/وسيط يُصدر فاتورة (مكتب تعقيب مثلاً)
    # بدل الصرف النقدي المباشر - يُملأ هذا الحقل بمورده فيُقترَح تلقائياً
    # على كل سجل رسوم لهذه الجهة، ويبقى قابلاً للتغيير في السجل نفسه.
    partner_id = fields.Many2one(
        'res.partner', string='المورد الافتراضي',
        domain=[('supplier_rank', '>', 0)], ondelete='restrict',
        help='المورد الذي تُسجَّل عليه فاتورة المشتريات حين يكون مسار '
             'السداد "فاتورة مشتريات" - يُقترَح تلقائياً عند اختيار هذه '
             'الجهة، ويمكن تغييره في سجل الرسوم نفسه.',
    )

    # _sql_constraints (الصيغة القديمة) لم تعد فعّالة إطلاقاً في هذا
    # الإصدار من Odoo - انظر الشرح الكامل في advance_reason.py.
    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد جهة حكومية أخرى بنفس الاسم بالفعل.',
    )


class BankSettlementGovernmentFeeType(models.Model):
    """نوع الرسوم الحكومية (نقل كفالة، تغيير مهنة...) - قائمة قابلة
    للتعديل والإضافة من المستخدم نفسه."""
    _name = 'bank.settlement.government.fee.type'
    _description = 'نوع الرسوم الحكومية'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)
    # رسوم التجديد (الإقامة، كرت العمل) لا تغطي من تاريخ سدادها بل من
    # تاريخ انتهاء الوثيقة: سداد مبكر بشهر كان يحمّل ذلك الشهر على
    # مصروف فترة لم تبدأ تغطيتها بعد، ويُنهي التغطية قبل موعدها بنفس
    # المدة. الخيار على النوع لا على كل سجل - "تجديد إقامة" يبدأ دائماً
    # من انتهاء الإقامة، وليس قراراً يُتخذ في كل مرة.
    coverage_start_source = fields.Selection(
        selection=[
            ('transfer', 'تاريخ التحويل'),
            ('residency', 'انتهاء الإقامة'),
            ('work_permit', 'انتهاء كرت العمل'),
        ],
        string='بداية تغطية الدفعة المقدمة', default='transfer', required=True,
        help='من أي تاريخ يبدأ جدول استحقاق "الدفعة المقدمة" لهذا النوع. '
             '"تاريخ التحويل" هو الافتراضي. "انتهاء الإقامة" يقرأ حقل '
             'أودو القياسي visa_expire على الموظف، و"انتهاء كرت العمل" '
             'يقرأ work_permit_expiration_date - وتبدأ التغطية في اليوم '
             'التالي للانتهاء (فلا يتداخل يوم مع الفترة السابقة).',
    )

    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد نوع رسوم آخر بنفس الاسم بالفعل.',
    )
