# -*- coding: utf-8 -*-
"""كشف حساب المندوب وطلب السلفة من تطبيقه.

المندوب يسأل سؤالين كل شهر: «كم عليّ؟» و«أريد سلفة». وكلاهما يمرّ
اليوم بمكالمة أو زيارة للمحاسبة. هنا يراهما في تطبيقه.

**ولا نتجاوز سير العمل:** الطلب يُنشأ مسودةً ثم يُستدعى
`action_submit_review()` من السداد البنكي نفسه - فيمرّ على فحوصه
(المبلغ، بيانات الصرف) ويدخل سلسلة الموافقات المعتادة. المندوب
**يطلب** ولا يعتمد.
"""
import logging

from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# الحالات التي تعني "طلب قائم لم يُحسم بعد".
OPEN_ADVANCE_STATES = ('draft', 'waiting_approval', 'pm_approved', 'approved')


class QuickDeliveryDriver(models.Model):
    _inherit = 'quick.delivery.driver'

    advance_ids = fields.One2many(
        'bank.settlement.advance', compute='_compute_advance_ids',
        string='سلف المندوب')
    open_advance_count = fields.Integer(
        string='طلبات سلف قائمة', compute='_compute_advance_ids')

    @api.depends('employee_id')
    def _compute_advance_ids(self):
        for rec in self:
            advances = rec._qd_advances()
            rec.advance_ids = advances
            rec.open_advance_count = len(advances.filtered(
                lambda adv: adv.state in OPEN_ADVANCE_STATES))

    def _qd_advances(self):
        """استعلام مباشر لا قراءة من الحقل المحسوب.

        الحقل المحسوب يُخزَّن في ذاكرة المعاملة: قراءتُه قبل إنشاء
        السلفة تُبقيه فارغاً بعدها، فيمرّ طلب ثانٍ من حارس "طلب واحد
        في كل مرة". المنطق يستعلم، والحقل للعرض وحده.
        """
        self.ensure_one()
        Advance = self.env['bank.settlement.advance'].sudo()
        if not self.employee_id:
            return Advance.browse()
        return Advance.search([('employee_id', '=', self.employee_id.id)],
                              order='id desc')

    def _qd_open_advances(self):
        self.ensure_one()
        return self._qd_advances().filtered(
            lambda adv: adv.state in OPEN_ADVANCE_STATES)

    # ------------------------------------------------------------------
    # الإعدادات
    # ------------------------------------------------------------------
    def _qd_accounting_env(self):
        """سياق محاسبي صالح للمسار العام.

        مسارات المندوب بـauth='none' تعمل **بلا مستخدم** (uid فارغ)، لا
        بمستخدم عام. و`sudo()` يرفع الصلاحية ولا يُعطي uid، فتبقى
        env.companies فارغة - فتُنتج استعلامات المحاسبة `IN ()` وتسقط
        بخطأ SQL. ولذلك نبني البيئة بمستخدم حقيقي ونُثبّت الشركة
        صراحةً: شركة الموظف، لا شركة افتراضية.
        """
        self.ensure_one()
        company = self.employee_id.sudo().company_id
        if not company:
            company = self.env['res.company'].sudo().search([], limit=1)
        env = self.env(user=SUPERUSER_ID,
                       context=dict(self.env.context,
                                    allowed_company_ids=company.ids))
        return self.with_env(env).with_company(company)

    @api.model
    def _qd_advance_max(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'quick_delivery.advance_max', '5000')
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            _logger.warning('حدّ السلفة غير صالح: %r', raw)
            return 5000.0

    @api.model
    def _qd_advance_one_at_a_time(self):
        return (self.env['ir.config_parameter'].sudo()
                .get_param('quick_delivery.advance_one_at_a_time', '1')
                .strip().lower() not in ('0', 'false', 'no'))

    # ------------------------------------------------------------------
    # كشف الحساب
    # ------------------------------------------------------------------
    def _qd_account_summary(self, limit=40):
        """كشف حساب المندوب - من دالة السداد البنكي نفسها لا من حساب
        موازٍ: رقمان مختلفان لنفس الرصيد أسوأ من لا رقم.

        إشارة الصافي كما في الكشف المطبوع: موجب = عليه للشركة،
        سالب = له على الشركة.
        """
        self.ensure_one()
        if not self.employee_id:
            return {
                'has_account': False,
                'reason': _('لا ملف موظف مرتبط بك - راجع الموارد البشرية.'),
            }
        scoped = self._qd_accounting_env()
        data = scoped.employee_id.sudo()._get_employee_statement_data()
        lines = data.get('lines') or []
        # الأحدث أولاً: المندوب يقرأ على شاشة جوال، وآخر حركة أهمّ من
        # أولها.
        recent = sorted(
            lines, key=lambda line: line.get('date') or fields.Date.today(),
            reverse=True)[:limit]
        return {
            'has_account': True,
            'net_total': data.get('net_total', 0.0),
            'total_debit': data.get('total_debit', 0.0),
            'total_credit': data.get('total_credit', 0.0),
            'line_count': len(lines),
            'lines': [{
                'date': fields.Date.to_string(line['date'])
                        if line.get('date') else '',
                'description': line.get('description') or '',
                'debit': line.get('debit') or 0.0,
                'credit': line.get('credit') or 0.0,
            } for line in recent],
            'cod_custody': self.cod_custody_balance,
            'today_earnings': self.today_earnings,
        }

    def _qd_advance_options(self):
        """ما يحتاجه التطبيق لبناء نموذج الطلب."""
        self.ensure_one()
        Reason = self.env['bank.settlement.advance.reason'].sudo()
        employee = self.employee_id.sudo()
        iban = ''
        if employee and 'bank_account_ids' in employee._fields:
            account = employee.bank_account_ids[:1]
            iban = account.acc_number if account else ''
        return {
            'can_request': bool(self.employee_id),
            'max_amount': self._qd_advance_max(),
            'one_at_a_time': self._qd_advance_one_at_a_time(),
            'open_count': len(self._qd_open_advances()),
            'reasons': [{'id': rec.id, 'name': rec.display_name}
                        for rec in Reason.search([])],
            'iban': iban,
            'phone': self.phone or '',
        }

    def _qd_advance_history(self, limit=20):
        self.ensure_one()
        labels = dict(
            self.env['bank.settlement.advance']._fields['state'].selection)
        return [{
            'name': adv.name,
            'amount': adv.amount,
            'date': fields.Date.to_string(adv.create_date.date())
                    if adv.create_date else '',
            'state': adv.state,
            'state_label': labels.get(adv.state, adv.state),
            'reason': adv.advance_reason_id.display_name or '',
            'is_open': adv.state in OPEN_ADVANCE_STATES,
        } for adv in self._qd_advances()[:limit]]

    # ------------------------------------------------------------------
    # رفع الطلب
    # ------------------------------------------------------------------
    def _qd_request_advance(self, amount, reason_id, method, detail,
                            note=''):
        """ينشئ طلب سلفة باسم المندوب ويُدخله سلسلة الموافقات.

        لا يُكتب أي اعتماد هنا: الإنشاء مسودة، ثم action_submit_review
        من السداد البنكي - بفحوصه هو. المندوب يطلب ولا يعتمد.
        """
        self.ensure_one()
        if not self.employee_id:
            raise UserError(_('لا ملف موظف مرتبط بك - راجع الموارد '
                              'البشرية قبل طلب السلفة.'))
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise UserError(_('المبلغ ليس رقماً.'))
        if amount <= 0:
            raise UserError(_('المبلغ يجب أن يكون أكبر من صفر.'))

        maximum = self._qd_advance_max()
        if maximum and amount > maximum:
            raise UserError(_(
                'الحدّ الأعلى للطلب من التطبيق %(max).2f ريال. '
                'لمبلغ أكبر راجع الإدارة.') % {'max': maximum})

        if self._qd_advance_one_at_a_time() and self._qd_open_advances():
            raise UserError(_(
                'لديك طلب سلفة لم يُحسم بعد. انتظر البتّ فيه قبل طلب '
                'آخر.'))

        reason = self.env['bank.settlement.advance.reason'].sudo().browse(
            int(reason_id or 0)).exists()
        if not reason:
            raise UserError(_('اختر سبب السلفة.'))

        if method not in ('bank_transfer', 'stc_pay'):
            raise UserError(_('اختر طريقة الصرف.'))
        detail = (detail or '').strip()
        if not detail:
            raise UserError(_('أدخل الآيبان أو رقم محفظة STC Pay.'))

        vals = {
            'employee_id': self.employee_id.id,
            'advance_reason_id': reason.id,
            'amount': amount,
            'payment_method': method,
            'notes': _('طُلبت من تطبيق المندوب%s') % (
                '\n%s' % note if note else ''),
        }
        if method == 'bank_transfer':
            vals['employee_iban'] = detail
        else:
            vals['stc_number'] = detail

        scoped = self._qd_accounting_env()
        advance = scoped.env['bank.settlement.advance'].sudo().create(vals)
        # فحوص السداد البنكي نفسها (المبلغ، بيانات الصرف) تُنفَّذ هنا،
        # وأي خطأ منها يصل المندوب برسالته الأصلية.
        advance.action_submit_review()
        self.invalidate_recordset(['advance_ids', 'open_advance_count'])
        _logger.info('طلب سلفة %s من تطبيق المندوب %s (%s) بمبلغ %.2f',
                     advance.name, self.name, self.employee_id.name, amount)
        return advance
