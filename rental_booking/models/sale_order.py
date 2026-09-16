# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    booking_source = fields.Selection(
        selection=[
            ('direct', 'حجز مباشر'),
            ('platform', 'جاذرن'),
        ],
        string='مصدر الحجز', copy=False, tracking=True,
    )
    # جهة التحصيل مستقلة عن المصدر عمداً: حجز جاذرن قد يُدفع في التطبيق
    # وقد يُدفع نقداً عند الوصول - وهي التي تحدد العميل، لا المصدر.
    booking_collected_by = fields.Selection(
        selection=[
            ('cash', 'نقداً من النزيل'),
            ('platform', 'عبر جاذرن'),
        ],
        string='جهة التحصيل', copy=False, tracking=True,
    )
    booking_reference = fields.Char(
        string='رقم الحجز', copy=False, tracking=True,
        help='رقم الحجز في المنصة - هو الرابط بين هذا الأمر وهوية النزيل '
             'الموثّقة عندها، وبه تُطابَق تحويلات المنصة مع حجوزاتكم.',
    )
    guest_name = fields.Char(string='اسم المستأجر', copy=False)
    guest_id_number = fields.Char(
        string='رقم هوية المستأجر', copy=False,
        help='يُطبع على الفاتورة الضريبية المبسطة مع الاسم والجوال.',
    )
    guest_mobile = fields.Char(string='جوال المستأجر', copy=False)
    guest_email = fields.Char(
        string='بريد المستأجر', copy=False,
        help='يُرسَل إليه عقد الإيجار - العميل المحاسبي "عميل نقدي" '
             'وبريده ليس بريد النزيل.',
    )
    contract_sent_date = fields.Datetime(
        string='تاريخ إرسال العقد', readonly=True, copy=False)

    # الحقول تُعرض على شاشة التأجير وحدها: أمر البيع العادي له عملاؤه
    # الحقيقيون. تُقرأ is_rental_order بأمان - يضيفها تطبيق التأجير
    # (نسخة مدفوعة) وقد لا يكون مثبَّتاً، فلا نعتمد عليها في التعريف.
    is_booking_order = fields.Boolean(
        string='أمر تأجير', compute='_compute_is_booking_order',
    )

    @api.depends('booking_source')
    def _compute_is_booking_order(self):
        # أو أن مصدر الحجز مملوء: يجعل الفحوص تسري متى استُخدمت الحقول
        # فعلاً، ويُبقي الموديول عاملاً وقابلاً للاختبار على نسخة بلا
        # تطبيق التأجير المدفوع.
        rental_field = 'is_rental_order' in self._fields
        for order in self:
            order.is_booking_order = bool(
                (rental_field and order.is_rental_order) or order.booking_source
            )

    def _get_booking_partner(self):
        """العميل المناسب لجهة التحصيل - أو سجل فارغ إن لم يُضبط بعد."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if self.booking_collected_by == 'cash':
            return company.rental_cash_partner_id
        if self.booking_collected_by == 'platform':
            return company.rental_platform_partner_id
        return self.env['res.partner']

    @api.onchange('booking_collected_by')
    def _onchange_booking_collected_by(self):
        """يضبط العميل تلقائياً - ولا يدهس عميلاً حقيقياً اختاره المستخدم
        (شركة أو حجز بفاتورة) إلا إن كان العميل الحالي أحد عميلَي الحجز."""
        for order in self:
            partner = order._get_booking_partner()
            if not partner:
                continue
            company = order.company_id or order.env.company
            booking_partners = (company.rental_cash_partner_id
                                | company.rental_platform_partner_id)
            if not order.partner_id or order.partner_id in booking_partners:
                order.partner_id = partner

    @api.onchange('booking_source')
    def _onchange_booking_source(self):
        # الحجز المباشر نقدي دائماً (لا منصة تحصّل عنه).
        if self.booking_source == 'direct' and not self.booking_collected_by:
            self.booking_collected_by = 'cash'
            self._onchange_booking_collected_by()

    @api.constrains('booking_reference', 'company_id')
    def _check_booking_reference_unique(self):
        """رقم الحجز مفتاح المطابقة مع المنصة - تكراره يعني أمرين يشيران
        لنفس الحجز، فتُحتسب إيراداته مرتين عند المطابقة."""
        for order in self:
            if not order.booking_reference:
                continue
            duplicate = self.search([
                ('id', '!=', order.id),
                ('booking_reference', '=', order.booking_reference),
                ('company_id', '=', order.company_id.id),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'رقم الحجز "%(ref)s" مستخدم بالفعل في الأمر %(order)s.'
                ) % {'ref': order.booking_reference, 'order': duplicate.name})

    def _check_booking_details(self):
        """يُفحص عند التأكيد لا عند الحفظ: الأمر يُبدأ غالباً قبل اكتمال
        بيانات الحجز، ومنعه من الحفظ يعطّل العمل بلا فائدة."""
        for order in self.filtered('is_booking_order'):
            if not order.booking_source:
                raise UserError(_('يجب تحديد "مصدر الحجز" قبل تأكيد الأمر.'))
            if not order.booking_collected_by:
                raise UserError(_('يجب تحديد "جهة التحصيل" قبل تأكيد الأمر.'))
            if order.booking_source == 'platform' and not order.booking_reference:
                raise UserError(_(
                    'حجوزات جاذرن تتطلب "رقم الحجز" - هو الرابط بهوية النزيل '
                    'عند المنصة، وبه تُطابَق تحويلاتها.'
                ))

    def action_confirm(self):
        self._check_booking_details()
        return super().action_confirm()

    # دفعات الحجز: تُقبَض عند الحجز وعند الوصول - أي قبل وجود الفاتورة
    # غالباً. تُرحَّل كل واحدة بتاريخها لحظة تسجيلها (فرصيد الصندوق صحيح
    # لحظة بلحظة، ولا يفشل الترحيل لو أُقفلت الفترة لاحقاً)، ثم تُطابَق
    # مع الفاتورة متى صدرت.
    booking_payment_ids = fields.One2many(
        'account.payment', 'booking_order_id', string='دفعات الحجز',
    )
    booking_payment_count = fields.Integer(compute='_compute_booking_amounts')
    booking_amount_paid = fields.Monetary(
        string='المدفوع', compute='_compute_booking_amounts',
        currency_field='currency_id',
    )
    booking_amount_due = fields.Monetary(
        string='المتبقي على المستأجر', compute='_compute_booking_amounts',
        currency_field='currency_id',
        help='إجمالي الحجز ناقص ما سُدّد - يعمل قبل إصدار الفاتورة وبعدها.',
    )

    @api.depends('amount_total', 'booking_payment_ids.state',
                 'booking_payment_ids.amount', 'invoice_ids.amount_residual',
                 'invoice_ids.state', 'invoice_ids.move_type')
    def _compute_booking_amounts(self):
        """المتبقي من مصدرين حسب المرحلة - لأن الفوترة قد تسبق الدفع وقد
        تليه (أفاد المستخدم أن الحالتين تقعان):

        - قبل صدور الفاتورة: إجمالي الحجز ناقص دفعاته المرحَّلة.
        - بعد صدورها: متبقي الفاتورة نفسها - وهو يشمل *كل* ما سُدّد، بما
          فيه دفعة سجّلها المحاسب من شاشة الفاتورة مباشرة لا من زر الحجز.
          الاعتماد على دفعات الحجز وحدها هنا كان سيُظهر الحجز غير مسدَّد
          بينما فاتورته مدفوعة.
        """
        for order in self:
            order.booking_payment_count = len(order.booking_payment_ids)
            invoices = order.invoice_ids.filtered(
                lambda m: m.state == 'posted'
                and m.move_type in ('out_invoice', 'out_refund'))
            if invoices:
                due = sum(invoices.mapped('amount_residual'))
            else:
                # الملغاة والمرفوضة لا تُحتسب، والمسودة لم تُقبَض بعد.
                posted_payments = order.booking_payment_ids.filtered(
                    lambda p: p.state in ('in_process', 'paid'))
                due = order.amount_total - sum(posted_payments.mapped('amount'))
            order.booking_amount_due = due
            order.booking_amount_paid = max(order.amount_total - due, 0.0)

    def action_register_booking_payment(self):
        self.ensure_one()
        Wizard = self.env['rental.booking.payment.register']
        if not self.env['account.journal'].search_count(
                Wizard._eligible_journal_domain(self.company_id)):
            raise UserError(
                'لا يوجد دفتر صندوق أو بنك متاح لشركة "%s" (ولا لشركتها '
                'الأم). أنشئ دفتراً من: المحاسبة ← الإعدادات ← دفاتر '
                'اليومية.' % self.company_id.display_name
            )
        return {
            'name': 'تسجيل دفعة على الحجز',
            'type': 'ir.actions.act_window',
            'res_model': 'rental.booking.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_view_booking_payments(self):
        self.ensure_one()
        return {
            'name': 'دفعات الحجز',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('booking_order_id', '=', self.id)],
        }

    # -- عقد الإيجار -----------------------------------------------------
    def _check_contract_ready(self):
        """العقد يُرسَل بعد تأكيد الحجز وقبض العربون - لا قبلهما.

        إرساله قبل التأكيد يعني عقداً على حجز قد لا يتم، وقبل العربون
        يعني التزاماً بلا مقابل مقبوض."""
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            raise UserError('يُرسَل العقد بعد تأكيد الحجز فقط.')
        if self.booking_amount_paid <= 0:
            raise UserError(
                'لم يُسجَّل أي مبلغ على هذا الحجز بعد. سجّل العربون أولاً '
                'من زر "تسجيل دفعة".'
            )

    def action_print_rental_contract(self):
        self.ensure_one()
        self._check_contract_ready()
        return self.env.ref('rental_booking.action_report_rental_contract').report_action(self)

    def action_send_rental_contract(self):
        """يرسل العقد لبريد المستأجر مع نسخة PDF مرفقة.

        البريد من حقل المستأجر لا من العميل: العميل المحاسبي مشترك
        ("عميل نقدي") فبريده - إن وُجد - ليس بريد النزيل، وإرساله إليه
        يعني إرسال عقود كل النزلاء لعنوان واحد."""
        self.ensure_one()
        self._check_contract_ready()
        if not self.guest_email:
            raise UserError(
                'لا يوجد بريد للمستأجر. أدخله في حقل "بريد المستأجر" على '
                'الحجز - أو اطبع العقد وسلّمه بطريقتكم المعتادة.'
            )
        template = self.env.ref(
            'rental_booking.mail_template_rental_contract', raise_if_not_found=False)
        if not template:
            raise UserError('قالب رسالة العقد غير موجود.')
        template.send_mail(
            self.id,
            email_values={'email_to': self.guest_email},
            force_send=True,
        )
        self.contract_sent_date = fields.Datetime.now()
        self.message_post(body=(
            'أُرسل عقد الإيجار إلى %s.' % self.guest_email))
        return True

    def _reconcile_booking_payments(self, invoices=None):
        """يطابق دفعات الحجز غير المطابَقة مع فواتيره المرحَّلة.

        يُستدعى من الطرفين لأن الترتيب يختلف من حجز لآخر (أفاد المستخدم
        أن الفاتورة قد تسبق الدفع وقد تليه): عند ترحيل الفاتورة
        (account_move._post) وعند تسجيل دفعة على حجز له فاتورة مرحَّلة
        بالفعل.

        المطابقة تكون بحساب الذمم المدينة، ومجمَّعة به: قد تختلف حسابات
        الذمم بين السجلات، وأودو لا تطابق سطرين بحسابين مختلفين."""
        self.ensure_one()
        if invoices is None:
            invoices = self.invoice_ids
        invoices = invoices.filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        if not invoices:
            return
        payments = self.booking_payment_ids.filtered(
            lambda p: p.state in ('in_process', 'paid') and p.move_id.state == 'posted')
        if not payments:
            return

        def open_receivable_lines(records):
            return records.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable'
                and not line.reconciled
            )

        payment_lines = open_receivable_lines(payments.move_id)
        invoice_lines = open_receivable_lines(invoices)
        for account in payment_lines.account_id:
            lines = (payment_lines + invoice_lines).filtered(
                lambda line: line.account_id == account)
            if len(lines.move_id) > 1:
                lines.reconcile()


    def _prepare_invoice(self):
        """ينقل بيانات المستأجر للفاتورة لتُطبع عليها.

        الفاتورة الضريبية *المبسطة* (بيع لفرد) لا تشترط بيانات المشتري
        نظاماً، ورمز QR يحمل بيانات البائع وحدها - فطباعة اسم المستأجر من
        هنا سليمة، ويبقى العميل المحاسبي "عميل نقدي" فلا تتضخم جهات
        الاتصال. أما الفاتورة الضريبية الكاملة (شركة برقم ضريبي) فتبقى
        بجهة اتصالها الحقيقية: حقول المستأجر تكون فارغة فلا يتغير شيء."""
        vals = super()._prepare_invoice()
        if self.guest_name or self.guest_id_number or self.guest_mobile:
            vals.update({
                'guest_name': self.guest_name,
                'guest_id_number': self.guest_id_number,
                'guest_mobile': self.guest_mobile,
            })
        if self.booking_reference:
            vals['booking_reference'] = self.booking_reference
        return vals
