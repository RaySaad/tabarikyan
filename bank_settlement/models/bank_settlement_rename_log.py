# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class BankSettlementRenameLog(models.Model):
    """سجل دائم لكل عملية "تعديل كود إداري" - يُنشأ قبل التعديل الفعلي
    مباشرة (انظر bank_settlement_mixin.action_admin_rename)، ويبقى حتى لو
    عُدِّل الكود مرة أخرى لاحقاً. نفس فلسفة bank.settlement.deletion.log
    تماماً: تجاوز حماية "الكود مقفول (readonly) بعد الإنشاء" أداة
    استثنائية يجب أن تترك أثراً كاملاً بمن فعلها ومتى ولماذا - وإلا أصبح
    التجاوز بلا أي مساءلة."""
    _name = 'bank.settlement.rename.log'
    _description = 'سجل تعديل الكود الإداري - سداد بنكي'
    _order = 'create_date desc'

    source_model = fields.Char(string='النموذج', required=True)
    old_code = fields.Char(string='الكود القديم', required=True)
    new_code = fields.Char(string='الكود الجديد', required=True)
    employee_name = fields.Char(string='الموظف / المندوب')
    reason = fields.Text(string='سبب التعديل', required=True)
    renamed_by = fields.Many2one('res.users', string='عدّله', required=True)

    def unlink(self):
        raise UserError(_(
            'لا يمكن حذف سجلات سجل تعديل الكود الإداري نفسها - هذا آخر '
            'أثر متبقٍ لعملية التعديل.'
        ))
