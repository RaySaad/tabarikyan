# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementPrepaidCategory(models.Model):
    """فئة "الدفعة المقدمة" (كرت عمل، إقامة فندقية...) - تُعَدّ مرة واحدة
    من إعدادات السداد البنكي، وتحدد الحسابات المحاسبية الثلاثة التي
    تحتاجها آلية الاستحقاق الدوري (انظر bank_settlement_mixin.py:
    _create_prepaid_schedule وprepaid_schedule.py):

    - prepaid_account_id: حساب "المصروفات المدفوعة مقدماً" (مثال:
      114001) - يُقيَّد عليه كامل المبلغ فوراً عند السداد الفعلي (مديناً)،
      ثم يُخفَّض تدريجياً بكل قيد استحقاق دوري (دائناً).
    - expense_account_id: حساب المصروف الفعلي الذي يُقيَّد عليه كل قيد
      استحقاق دوري (مديناً) - نفس نوع الحساب الذي كان سيُستخدم لو كان
      المبلغ يُصرَف فوراً بلا "دفعة مقدمة" (linked_account_id العادي).
    - journal_id: دفتر اليومية الذي تُسجَّل فيه قيود الاستحقاق الدورية
      تحديداً (قد يختلف عن دفتر السداد البنكي الفعلي).

    نموذج مملوك بالكامل لهذا الموديول - لا يعتمد على أي تطبيق "أصول"
    خارجي (لا om_account_asset ولا account_asset الأصلي بـEnterprise)،
    تفادياً لمشكلة عدم توفر الأول على خادم Odoo.sh الفعلي، وتعقيد
    الاعتماد على بنية الثاني الداخلية غير الموثَّقة."""
    _name = 'bank.settlement.prepaid.category'
    _description = 'فئة الدفعة المقدمة'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    prepaid_account_id = fields.Many2one(
        'account.account', string='حساب المصروفات المدفوعة مقدماً',
        required=True,
        help='يُقيَّد عليه كامل مبلغ الدفعة مديناً فور السداد الفعلي '
             '(مقابل دفتر اليومية البنكي)، ثم يُخفَّض تدريجياً دائناً '
             'بكل قيد استحقاق دوري لاحق.',
    )
    expense_account_id = fields.Many2one(
        'account.account', string='حساب المصروف الفعلي', required=True,
        help='يُقيَّد عليه مبلغ كل قيد استحقاق دوري مديناً (مقابل حساب '
             'المصروفات المدفوعة مقدماً أعلاه).',
    )
    journal_id = fields.Many2one(
        'account.journal', string='دفتر يومية الاستحقاق', required=True,
        help='الدفتر الذي تُسجَّل فيه قيود الاستحقاق الدورية تحديداً - '
             'غالباً دفتر "قيود عامة"/"استحقاقات" مخصَّص، وليس دفتر '
             'السداد البنكي الفعلي.',
    )
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد فئة دفعة مقدمة أخرى بنفس الاسم بالفعل.',
    )
