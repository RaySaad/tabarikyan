# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# نسبة تحمّل الفرع الافتراضية حسب نتيجة تحديد المسؤولية.
# "المندوب": يتحملها الفرع ثم يستردّها من مندوبه عبر "تحويل مركبة"
# في السداد البنكي. "طرف آخر": على التأمين/الطرف المقابل.
# "غير محدد": لا تُحمَّل حتى تُحسم.
_SHARE_BY_RESPONSIBILITY = {
    'employee': 100.0,
    'third_party': 0.0,
    'shared': 50.0,
    'undetermined': 0.0,
}


class FleetAccidentReport(models.Model):
    _inherit = 'fleet.accident.report'

    actual_cost = fields.Monetary(
        string='التكلفة الفعلية للإصلاح', tracking=True,
        help='تُملأ بعد الإصلاح - وهي أساس التحميل على الفرع، لا التقدير '
             'المبدئي.',
    )
    branch_share_percent = fields.Float(
        string='نسبة تحمّل الفرع %', tracking=True,
        compute='_compute_branch_share_percent', store=True, readonly=False,
        help='تُقترح من تحديد المسؤولية وتبقى قابلة للتعديل قبل التحميل.',
    )
    branch_charge_amount = fields.Monetary(
        string='المحمَّل على الفرع', compute='_compute_branch_charge_amount',
        store=True,
    )
    close_date = fields.Date(
        string='تاريخ الإغلاق', readonly=True, copy=False,
        help='يُسجَّل عند إغلاق البلاغ - وبه يُحدَّد شهر التحميل.',
    )
    rental_charge_line_id = fields.Many2one(
        'fleet.branch.rental.charge.line', string='سطر التحميل',
        readonly=True, copy=False, ondelete='set null',
        help='يُملأ عند توليد تحميل الشهر - ويمنع تحميل البلاغ مرتين.',
    )

    @api.depends('responsibility')
    def _compute_branch_share_percent(self):
        for rec in self:
            rec.branch_share_percent = _SHARE_BY_RESPONSIBILITY.get(
                rec.responsibility, 0.0)

    @api.depends('actual_cost', 'branch_share_percent')
    def _compute_branch_charge_amount(self):
        for rec in self:
            rec.branch_charge_amount = rec.actual_cost * rec.branch_share_percent / 100.0

    def action_close(self):
        res = super().action_close()
        self.filtered(lambda r: not r.close_date).write({
            'close_date': fields.Date.context_today(self),
        })
        return res

    def action_reset_draft(self):
        """إعادة البلاغ لمسودة تُلغي تاريخ إغلاقه - وإلا بقي محسوباً في
        شهرٍ أُغلق فيه ثم أُعيد فتحه."""
        for rec in self:
            if rec.rental_charge_line_id:
                raise UserError(_(
                    'البلاغ "%(name)s" محمَّل بالفعل على الفرع ضمن %(charge)s - '
                    'ألغِ ذلك التحميل أولاً إن أردت إعادة فتحه.'
                ) % {'name': rec.name,
                     'charge': rec.rental_charge_line_id.charge_id.name})
        res = super().action_reset_draft()
        self.write({'close_date': False})
        return res
