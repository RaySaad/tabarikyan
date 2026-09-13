# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSettlementMedicalInsuranceType(models.Model):
    """نوع رسوم التأمين الطبي (تأمين طبي، فحص طبي...) - قائمة قابلة
    للتعديل والإضافة من المستخدم نفسه، بدل قائمة ثابتة بالكود."""
    _name = 'bank.settlement.medical.insurance.type'
    _description = 'نوع رسوم التأمين الطبي'
    _order = 'sequence, name'

    name = fields.Char(string='الاسم', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    active = fields.Boolean(default=True)
    # حساب المصروف الافتراضي لهذا النوع - يُملأ في "الحساب المرتبط" لحظة
    # اعتماد السجل (أول لحظة ينفتح فيها الحقل للمحاسب، انظر
    # _get_bank_fields_editable_state)، ويبقى قابلاً للتعديل. النوع
    # الواحد غالباً يُقيَّد على نفس الحساب في كل مرة، فاختياره يدوياً كل
    # مرة يفتح باب خطأ بلا فائدة.
    account_id = fields.Many2one(
        'account.account', string='حساب المصروف الافتراضي',
        ondelete='restrict',
        help='يُقترَح تلقائياً في "الحساب المرتبط" عند اعتماد السجل، '
             'ويمكن تغييره قبل الإتمام.',
    )

    # _sql_constraints (الصيغة القديمة) لم تعد فعّالة إطلاقاً في هذا
    # الإصدار من Odoo - انظر الشرح الكامل في advance_reason.py.
    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد نوع رسوم آخر بنفس الاسم بالفعل.',
    )
