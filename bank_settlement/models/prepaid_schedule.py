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
    # ondelete='restrict' على الحقلين: بدونها (والافتراضي 'set null') كان
    # حذف الموظف أو حذف فئة الدفعة المقدمة من الإعدادات يُفرغ الحقل بصمت
    # على أسطر استحقاق لم تُرحَّل بعد - فتفشل المهمة المجدولة لاحقاً بلا
    # أي أثر ظاهر للمستخدم (لا موظف = لا توزيع تحليلي، ولا فئة = لا
    # حسابات ولا دفتر يومية). نفس صنف الثغرة الحقيقية التي سبّبت فقدان
    # بيانات فعلياً في employee_id بـbank_settlement_mixin.
    employee_id = fields.Many2one(
        'hr.employee', string='المندوب', required=True, index=True,
        ondelete='restrict',
        help='يُستخدَم لاشتقاق منصته الفعلية (كيتا/هنقرستيشن/جاهز) في '
             'تاريخ استحقاق هذا السطر تحديداً - انظر '
             'hr.employee._get_platform_analytic_distribution.',
    )
    category_id = fields.Many2one(
        'bank.settlement.prepaid.category', string='فئة الدفعة المقدمة',
        required=True, ondelete='restrict',
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
        selection=[
            ('draft', 'لم يستحق بعد'),
            ('posted', 'مرحّل'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, copy=False,
    )
    move_id = fields.Many2one(
        'account.move', string='قيد الاستحقاق', readonly=True, copy=False,
    )
    # ثغرة حقيقية كشفها سؤال المستخدم: سطر يبقى "لم يستحق بعد" بلا أي
    # سبب ظاهر - سواء لأن المهمة المجدولة لم تعمل أصلاً (بيئة Staging
    # في Odoo.sh تُعطّل المهام المجدولة)، أو لأنها عملت وفشلت (قفل فترة
    # محاسبية، حساب غير صالح...) فسُجّل الخطأ في سجلات الخادم وحدها ولم
    # يره المستخدم إطلاقاً. الآن يُعرَض السبب على السطر نفسه.
    last_attempt_date = fields.Datetime(
        string='آخر محاولة ترحيل', readonly=True, copy=False,
    )
    last_error = fields.Text(
        string='سبب تعذّر الترحيل', readonly=True, copy=False,
        help='يُملأ تلقائياً عند فشل محاولة الترحيل - فراغه مع بقاء '
             'الحالة "لم يستحق بعد" رغم انتهاء الفترة يعني أن المهمة '
             'المجدولة لم تعمل أصلاً بعد.',
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
            if line.state in ('posted', 'cancel'):
                continue
            # سطر بمبلغ صفر (حالة حدّية: فترة يوم واحد بمبلغ ضئيل جداً
            # يتلاشى بالتقريب) كان سيُنتج قيداً محاسبياً فارغاً بلا أي
            # معنى - يُلغى بدل ترحيله.
            if not line.amount:
                line.write({'state': 'cancel'})
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
            line.write({
                'move_id': move.id, 'state': 'posted',
                'last_attempt_date': fields.Datetime.now(), 'last_error': False,
            })

    def action_post_now(self):
        """ترحيل فوري يدوي - لا يعتمد على المهمة المجدولة إطلاقاً (مفيد
        خصوصاً في بيئة Staging التي تُعطّل Odoo.sh مهامها المجدولة، أو
        لمعالجة سطر تعثّر ترحيله سابقاً). أي خطأ يظهر للمستخدم مباشرة
        بدل أن يُدفَن في سجلات الخادم."""
        for line in self:
            if line.state == 'posted':
                raise UserError(_('السطر "%s" مُرحَّل بالفعل.') % line.name)
            if line.state == 'cancel':
                raise UserError(_(
                    'السطر "%s" ملغى - أعِد تفعيله أولاً إن أردت ترحيله.'
                ) % line.name)
            if line.period_end_date > fields.Date.context_today(line):
                raise UserError(_(
                    'فترة السطر "%(name)s" لم تنتهِ بعد (تنتهي في '
                    '%(end)s) - لا يصح ترحيل مصروف فترة لم تكتمل.'
                ) % {'name': line.name, 'end': line.period_end_date})
        self._post_entry()

    def action_cancel_line(self):
        """إلغاء سطر استحقاق لم يُرحَّل بعد - يوقف ترحيله تلقائياً في
        المستقبل. لم تكن هناك أي وسيلة لإيقاف جدول استحقاق بُني بالخطأ أو
        لم يعد ذا معنى (مندوب غادر، رسوم عُكست): الحذف ممنوع عمداً
        (سجل تدقيق) والمهمة المجدولة كانت ستستمر بالترحيل إلى ما لا
        نهاية - ثغرة تشغيلية حقيقية.

        القيود المُرحَّلة فعلاً لا تُمَس (تُعكَس محاسبياً عند اللزوم)، كما
        أن رصيد "المصروفات المدفوعة مقدماً" المتبقي يبقى كما هو ويحتاج
        معالجة محاسبية يدوية - انظر التنبيه في الواجهة."""
        for line in self:
            if line.state == 'posted':
                raise UserError(_(
                    'لا يمكن إلغاء سطر مُرحَّل بالفعل (%s) - اعكس قيده '
                    'المحاسبي بدلاً من ذلك إن لزم.'
                ) % line.name)
        self.write({'state': 'cancel'})

    def _reverse_posted_entry(self, reason):
        """يعكس قيد سطر استحقاق مُرحَّل، ويضع السطر في "ملغى".

        داخلي فقط: يُستدعى من مسار "إلغاء التنفيذ وتصحيح" في
        bank.settlement.mixin حين يُلغى تنفيذ سجل دفعة مقدمة بأكمله -
        وإلا بقيت قيود الفترات المرحَّلة قائمةً في الدفاتر بعد عكس
        القيد الأصلي الذي أنشأها. لا يوجد زر له بالواجهة عمداً: عكس
        فترة واحدة منفردة قرار محاسبي مستقل يخص المحاسب، أما هنا فالسجل
        كله يُلغى دفعةً واحدة.

        is_bank_settlement_move يُضبط صراحةً على العكسي لنفس سبب القيد
        الرئيسي (الحقل copy=False) - انظر _reverse_settlement_move."""
        self.ensure_one()
        move = self.move_id.sudo()
        if self.state != 'posted' or not move or move.state != 'posted':
            return self.env['account.move']
        reverse = move._reverse_moves([{
            'date': fields.Date.context_today(self),
            'ref': _('عكس %(name)s - %(reason)s') % {'name': move.name, 'reason': reason},
        }], cancel=True)
        reverse.is_bank_settlement_move = True
        self.sudo().write({'state': 'cancel'})
        return reverse

    def action_reset_to_draft(self):
        """إعادة سطر ملغى لحالة "لم يستحق بعد" - للتراجع عن إلغاء خاطئ."""
        for line in self:
            if line.state != 'cancel':
                raise UserError(_('الإعادة متاحة للأسطر الملغاة فقط.'))
        self.write({'state': 'draft'})

    @api.model
    def _cron_generate_due_entries(self):
        """تعمل يومياً (انظر data/prepaid_cron_data.xml) - ترحّل تلقائياً
        كل سطر انتهت فترته فعلياً (period_end_date، وليس period_start_date
        - ثغرة حقيقية اكتُشفت من الاستخدام الفعلي: كانت تُرحِّل السطر بمجرد
        *بداية* فترته لا نهايتها، فينتج قيد بتاريخ مستقبلي لم يأتِ بعد)
        ولم يُرحَّل بعد، بلا أي مراجعة بشرية (طلب صريح)."""
        today = fields.Date.context_today(self)
        due_lines = self.sudo().search([
            ('state', '=', 'draft'),
            ('period_end_date', '<=', today),
        ])
        for line in due_lines:
            # نقطة حفظ لكل سطر على حدة: بدونها كان أي فشل *بعد* إنشاء
            # القيد وقبل ربطه بالسطر (مثال: قفل فترة محاسبية، حساب غير
            # صالح) يترك القيد المُنشأ قائماً كمسودة معلَّقة، ويبقى السطر
            # "لم يستحق بعد" - فتُنشئ المهمة قيداً جديداً في اليوم التالي
            # وهكذا: قيود مكرَّرة تتراكم بلا حد. الآن يُتراجَع عن أي أثر
            # جزئي بالكامل، ويُعاد المحاولة نظيفاً في اليوم التالي.
            try:
                with self.env.cr.savepoint():
                    line._post_entry()
            except Exception as exc:
                _logger.exception(
                    'bank_settlement: تعذّر ترحيل سطر استحقاق الدفعة '
                    'المقدمة #%s تلقائياً', line.id,
                )
                # يُكتب *بعد* التراجع عن نقطة الحفظ - فيبقى محفوظاً حتى
                # مع إلغاء كل ما فعله الترحيل الفاشل، ليراه المستخدم على
                # السطر بدل بقائه "لم يستحق بعد" بلا تفسير.
                line.sudo().write({
                    'last_attempt_date': fields.Datetime.now(),
                    'last_error': str(exc)[:2000],
                })
