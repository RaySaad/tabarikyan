# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    fleet_rental_start_date = fields.Date(
        string='بداية احتساب الأجرة',
        help='لا يُحتسب أي تحميل قبل هذا التاريخ - البيانات الأقدم تبقى '
             'سجلات للتدقيق والمراجعة بلا أثر محاسبي.',
    )
    # الحسابات يحددها المحاسب، ولكل شركة حساباتها - لذلك حقول على الشركة
    # نفسها لا إعداد عام واحد.
    fleet_rental_journal_id = fields.Many2one(
        'account.journal', string='دفتر قيود التحميل',
        domain="[('type', '=', 'general'), ('company_id', 'parent_of', id)]",
    )
    fleet_rental_expense_account_id = fields.Many2one(
        'account.account', string='حساب مصروف أجرة السيارات',
        help='يُستخدَم في قيد الفرع المستأجر (مدين).',
    )
    fleet_rental_interco_account_id = fields.Many2one(
        'account.account', string='الحساب الجاري بين الفروع',
        help='الطرف المقابل في الجهتين - يتقاصّ عند توحيد الميزانية.',
    )
    fleet_rental_income_account_id = fields.Many2one(
        'account.account', string='حساب استرداد تكلفة الأسطول',
        help='يُستخدَم في قيد شركة الأسطول (دائن).',
    )

    def _get_fleet_rental_config(self, fname):
        """قيمة الإعداد من الشركة، وإلا من شركتها الأم - الفروع عادةً
        تشارك الأم دليل حساباتها فلا داعي لتكرار الضبط في كل فرع."""
        self.ensure_one()
        for company in self.sudo().parent_ids[::-1]:
            value = company[fname]
            if value:
                return value
        return self[fname]
