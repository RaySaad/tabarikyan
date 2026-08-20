# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class BankSettlementDeletionLog(models.Model):
    """سجل دائم لكل عملية "حذف نهائي إداري" - يُنشأ قبل الحذف الفعلي
    مباشرة (انظر bank_settlement_mixin.action_admin_force_delete)، ويبقى
    بعد اختفاء السجل الأصلي نفسه. الهدف: عندما نتجاوز عمداً حماية "لا
    حذف بعد مغادرة مسودة" لتنظيف بيانات خاطئة، يجب أن يبقى أثر كامل بمن
    فعل ذلك ومتى ولماذا - وإلا أصبح التجاوز بلا أي مساءلة."""
    _name = 'bank.settlement.deletion.log'
    _description = 'سجل الحذف النهائي الإداري - سداد بنكي'
    _order = 'create_date desc'

    source_model = fields.Char(string='النموذج', required=True)
    record_name = fields.Char(string='الكود', required=True)
    employee_name = fields.Char(string='الموظف / المندوب')
    amount = fields.Monetary(string='المبلغ')
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id,
    )
    state_at_deletion = fields.Char(string='الحالة عند الحذف')
    move_name = fields.Char(string='القيد المحاسبي المرتبط')
    move_status_at_deletion = fields.Char(
        string='مصير القيد المحاسبي',
        help='"عُكس ورُحِّل" إن كان القيد الأصلي مرحّلاً (Posted) وقت '
             'الحذف - القيد الأصلي يبقى في دفاتر المحاسبة، ويُضاف له قيد '
             'عكسي مرحّل يُصفّر أثره المالي. "حُذف مباشرة" إن كان القيد '
             'لا يزال مسودة (لا أثر محاسبي رسمي بعد).',
    )
    reason = fields.Text(string='سبب الحذف', required=True)
    deleted_by = fields.Many2one('res.users', string='حذفه', required=True)

    def unlink(self):
        raise UserError(_(
            'لا يمكن حذف سجلات سجل الحذف الإداري نفسها - هذا آخر أثر '
            'متبقٍ لعملية الحذف النهائي.'
        ))
