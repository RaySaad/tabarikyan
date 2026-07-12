# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrEmployeeCostType(models.Model):
    _name = 'hr.employee.cost.type'
    _description = 'نوع تكلفة الموظف (تجديد إقامة، نقل، أخرى...)'
    _order = 'sequence, id'

    name = fields.Char(string='اسم النوع', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    category = fields.Selection(
        selection=[
            ('government', 'مدفوعات حكومية'),
            ('transfer', 'نقل بين المنصات'),
            ('other', 'أخرى'),
        ],
        string='التصنيف',
        default='other',
        required=True,
        help='التصنيف يحدد دفتر اليومية المقترح تلقائياً، ويُستخدم للفلترة '
             'والتجميع في التقارير (مثال: كل "المدفوعات الحكومية" مع بعض).',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='الجهة الافتراضية (المورّد)',
        help='الجهة/المورّد الذي تُصدَر له فاتورة المورد افتراضياً لهذا '
             'النوع (مثال: الجوازات، مؤسسة التأمينات GOSI...). يمكن '
             'تغييره لكل سجل تكلفة عند الحاجة.',
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='حساب المصروف',
        required=True,
        help='الحساب المحاسبي لسطر فاتورة المورد. يُوزَّع تحليلياً تلقائياً '
             'على حساب المشروع/المنصة عند الرفع للمحاسبة.',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='دفتر فواتير الموردين',
        domain="[('type', '=', 'purchase')]",
        help='دفتر اليومية (من نوع مشتريات) الذي ستُنشأ عليه فاتورة '
             'المورد. اترك فارغاً لاستخدام دفتر المشتريات الافتراضي للشركة.',
    )
    active = fields.Boolean(string='نشط', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='الشركة',
        default=lambda self: self.env.company,
    )

    @api.onchange('category')
    def _onchange_category(self):
        if self.category == 'government' and not self.journal_id:
            journal = self.env.ref(
                'recruitment_workflow.journal_government_payments', raise_if_not_found=False,
            )
            if journal:
                self.journal_id = journal.id
