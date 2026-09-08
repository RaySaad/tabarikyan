# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    # الوجه العكسي لعلاقة أعضاء الفريق - علاقة حقيقية بنفس جدول الربط،
    # فتُستخدَم مباشرة داخل قواعد السجلات (user.accounting_team_ids)
    # بلا أي حساب أو استعلام إضافي عند كل تحقق صلاحية.
    accounting_team_ids = fields.Many2many(
        'account.team', 'account_team_users_rel', 'user_id', 'team_id',
        string='الفرق المحاسبية',
        help='الفرق التي ينتمي إليها المستخدم - تحدد الدفاتر التي يراها '
             'وقيودها. لا أثر لها على مدير المحاسبة (معفى).',
    )
