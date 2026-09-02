# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BankSettlementPrepaidLine(models.Model):
    """سطر واحد من جدول استحقاق "دفعة مقدمة" (كرت عمل، إقامة فندقية...) -
    نموذج مملوك بالكامل لهذا الموديول (بلا أي اعتماد على تطبيق "أصول"
    خارجي)، يحل محل ما كان مخطَّطاً بالاعتماد عليه في om_account_asset/
    account_asset الأصلي. انظر شرح التصميم الكامل في
    bank_settlement_mixin.py: _create_prepaid_schedule/
    _compute_prepaid_schedule_lines، وhr_employee.py:
    _settle_prepaid_lines_on_transfer.

    res_model/res_id (بنفس نمط ir.attachment) تربط السطر بسجل السداد
    البنكي المصدر - عبر أي من الشاشات الخمس (سلفة/رسوم حكومية/تحويل
    مركبة/تأمين طبي/تصفية مندوب)، بدل حقل Many2one منفصل لكل نموذج."""
    _name = 'bank.settlement.prepaid.line'
    _description = 'سطر استحقاق دفعة مقدمة'
    _order = 'period_start_date, sequence'

    res_model = fields.Char(string='نموذج المصدر', required=True, index=True)
    res_id = fields.Integer(string='معرّف سجل المصدر', required=True, index=True)

    name = fields.Char(string='الوصف')
    sequence = fields.Integer(string='الترتيب', default=10)
    employee_id = fields.Many2one(
        'hr.employee', string='المندوب', required=True, index=True,
        help='يُستخدَم لاشتقاق منصته الفعلية (كيتا/هنقرستيشن/جاهز) في '
             'تاريخ استحقاق هذا السطر تحديداً - انظر '
             'hr.employee._get_platform_analytic_distribution.',
    )
    category_id = fields.Many2one(
        'bank.settlement.prepaid.category', string='فئة الدفعة المقدمة',
        required=True,
        help='تحدد الحسابات المحاسبية (المصروف الفعلي، المصروفات '
             'المدفوعة مقدماً، دفتر اليومية) المستخدَمة عند ترحيل هذا '
             'السطر - انظر prepaid_category.py.',
    )
    company_id = fields.Many2one('res.company', string='الشركة', required=True)
    currency_id = fields.Many2one('res.currency', string='العملة', required=True)

    period_start_date = fields.Date(string='بداية الفترة', required=True)
    period_end_date = fields.Date(string='نهاية الفترة', required=True)
    amount = fields.Monetary(string='المبلغ', required=True)

    state = fields.Selection(
        selection=[('draft', 'لم يستحق بعد'), ('posted', 'مرحّل')],
        string='الحالة', default='draft', required=True, copy=False,
    )
    move_id = fields.Many2one(
        'account.move', string='قيد الاستحقاق', readonly=True, copy=False,
    )

    def action_view_source(self):
        """يفتح سجل السداد البنكي المصدر لهذا السطر."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('لم يُرحَّل هذا السطر بعد.'))
        return {
            'name': 'قيد الاستحقاق',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def _get_settlement_partner_id(self):
        self.ensure_one()
        return self.employee_id._get_personal_partner().id if self.employee_id else False

    def _post_entry(self):
        """يرحّل هذا السطر فعلياً: يبني قيداً (مديناً حساب المصروف
        الفعلي / دائناً حساب المصروفات المدفوعة مقدماً) بمبلغ هذا السطر
        فقط، بتوزيع تحليلي مُحسَب *الآن* (وقت الترحيل الفعلي، وليس وقت
        بناء الجدول كاملاً) من منصة المندوب الفعلية بتاريخ نهاية هذه
        الفترة - جوهر الحل: بما أن كل سطر يُرحَّل فقط عند استحقاقه فعلياً
        (عبر _cron_generate_due_entries أدناه، أو فوراً عند تسوية نقل
        منصة - انظر hr_employee.py)، فإن أي نقل منصة سابق لتاريخ الترحيل
        يُقرأ صحيحاً هنا تلقائياً، بلا أي تعديل يدوي على سطور مستقبلية.

        تنبيه هام: analytic_distribution يُضبط صراحة على *كِلا* سطري
        القيد (وليس سطر المصروف فقط) - وإلا يتدخل نموذج account.analytic.
        distribution.model العام (يُحدِّثه recruitment_workflow.hr_employee.
        _sync_partner_analytic_distribution تلقائياً لكل شريك عند أي نقل
        منصة فعلي، لأغراض أخرى) فيملأ السطر الآخر تلقائياً بتوزيع *المنصة
        الحالية وقت الترحيل* بدل توزيع تاريخ الفترة الصحيح - ثغرة حقيقية
        اكتُشفت أثناء اختبار تسوية نقل منصة (سطر المصروف صحيح بتوزيع
        المنصة القديمة، لكن السطر المقابل كان يظهر بتوزيع المنصة الجديدة
        خطأً)."""
        for line in self:
            if line.state == 'posted':
                continue
            category = line.category_id
            distribution = line.employee_id._get_platform_analytic_distribution(
                line.period_end_date
            )
            move_vals = {
                'journal_id': category.journal_id.id,
                'company_id': line.company_id.id,
                'is_bank_settlement_move': True,
                'date': line.period_end_date,
                'ref': line.name,
                'line_ids': [
                    (0, 0, {
                        'name': line.name,
                        'account_id': category.expense_account_id.id,
                        'partner_id': line._get_settlement_partner_id(),
                        'debit': line.amount,
                        'credit': 0.0,
                        'analytic_distribution': distribution,
                    }),
                    (0, 0, {
                        'name': line.name,
                        'account_id': category.prepaid_account_id.id,
                        'partner_id': line._get_settlement_partner_id(),
                        'debit': 0.0,
                        'credit': line.amount,
                        'analytic_distribution': distribution,
                    }),
                ],
            }
            move = self.env['account.move'].sudo().create(move_vals)
            move.action_post()
            line.write({'move_id': move.id, 'state': 'posted'})

    @api.model
    def _cron_generate_due_entries(self):
        """تعمل يومياً (انظر data/prepaid_cron_data.xml) - ترحّل تلقائياً
        كل سطر حان تاريخ استحقاقه (بداية فترته وصلت أو مضت) ولم يُرحَّل
        بعد، بلا أي مراجعة بشرية (طلب صريح)."""
        today = fields.Date.context_today(self)
        due_lines = self.sudo().search([
            ('state', '=', 'draft'),
            ('period_start_date', '<=', today),
        ])
        for line in due_lines:
            try:
                line._post_entry()
            except Exception:
                _logger.exception(
                    'bank_settlement: تعذّر ترحيل سطر استحقاق الدفعة '
                    'المقدمة #%s تلقائياً', line.id,
                )
