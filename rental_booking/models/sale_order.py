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
    guest_name = fields.Char(string='اسم النزيل', copy=False)
    guest_mobile = fields.Char(string='جوال النزيل', copy=False)

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
