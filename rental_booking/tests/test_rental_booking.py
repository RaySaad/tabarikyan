# -*- coding: utf-8 -*-
from ast import literal_eval

from odoo.exceptions import UserError, ValidationError
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRentalBooking(TransactionCase):
    """حجوزات الشاليهات بعميلين ثابتين ورقم حجز - بدل جهة اتصال لكل نزيل."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.cash = cls.env.ref('rental_booking.partner_rental_cash')
        cls.platform = cls.env.ref('rental_booking.partner_rental_gathern')
        cls.product = cls.env['product.product'].create({
            'name': 'شاليه اختبار', 'type': 'service', 'list_price': 500.0})

    def _order(self, **vals):
        return self.env['sale.order'].create(dict({
            'partner_id': self.cash.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})],
        }, **vals))

    # ---- الإعداد ----
    def test_default_partners_are_set_on_the_company(self):
        """post_init_hook يملؤهما، فلا يبدأ المستخدم بإعداد يدوي."""
        self.assertEqual(self.company.rental_cash_partner_id, self.cash)
        self.assertEqual(self.company.rental_platform_partner_id, self.platform)

    # ---- ضبط العميل تلقائياً ----
    def test_cash_collection_sets_the_cash_customer(self):
        # سجل غير محفوظ: العميل مطلوب على أمر البيع، والحالة الواقعية هي
        # اختيار جهة التحصيل في الشاشة قبل الحفظ والعميل ما زال فارغاً.
        order = self.env['sale.order'].new({})
        order.booking_collected_by = 'cash'
        order._onchange_booking_collected_by()
        self.assertEqual(order.partner_id, self.cash)

    def test_platform_collection_sets_the_platform_customer(self):
        """المدفوع عبر جاذرن دَين عليها حتى تحوّله - لا على النزيل."""
        order = self._order()
        order.booking_collected_by = 'platform'
        order._onchange_booking_collected_by()
        self.assertEqual(order.partner_id, self.platform)

    def test_a_real_customer_is_never_overwritten(self):
        """حجز شركة بفاتورة: العميل الحقيقي يبقى كما هو."""
        real = self.env['res.partner'].create({'name': 'شركة مستأجرة'})
        order = self._order(partner_id=real.id)
        order.booking_collected_by = 'cash'
        order._onchange_booking_collected_by()
        self.assertEqual(order.partner_id, real)

    def test_switching_collection_switches_between_booking_partners(self):
        order = self._order()
        order.booking_collected_by = 'cash'
        order._onchange_booking_collected_by()
        order.booking_collected_by = 'platform'
        order._onchange_booking_collected_by()
        self.assertEqual(order.partner_id, self.platform)

    def test_direct_booking_defaults_to_cash(self):
        order = self.env['sale.order'].new({})
        order.booking_source = 'direct'
        order._onchange_booking_source()
        self.assertEqual(order.booking_collected_by, 'cash')
        self.assertEqual(order.partner_id, self.cash)

    # ---- رقم الحجز ----
    def test_booking_reference_must_be_unique(self):
        """تكراره يعني أمرين لنفس الحجز، فتُحتسب إيراداته مرتين."""
        self._order(booking_source='platform', booking_collected_by='platform',
                    booking_reference='GT-1001')
        with self.assertRaises(ValidationError):
            self._order(booking_source='platform', booking_collected_by='platform',
                        booking_reference='GT-1001')

    def test_cancelled_order_frees_its_reference(self):
        first = self._order(booking_source='platform', booking_collected_by='platform',
                            booking_reference='GT-2002')
        first._action_cancel()
        self._order(booking_source='platform', booking_collected_by='platform',
                    booking_reference='GT-2002')

    def test_empty_reference_is_not_treated_as_duplicate(self):
        self._order(booking_source='direct', booking_collected_by='cash')
        self._order(booking_source='direct', booking_collected_by='cash')

    # ---- الفحص عند التأكيد ----
    def test_platform_booking_requires_a_reference_to_confirm(self):
        order = self._order(booking_source='platform', booking_collected_by='platform')
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_collection_is_required_to_confirm(self):
        order = self._order(booking_source='direct')
        order.booking_collected_by = False
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_complete_booking_confirms(self):
        order = self._order(booking_source='platform', booking_collected_by='platform',
                            booking_reference='GT-3003', guest_name='نزيل تجريبي',
                            guest_mobile='0501234567')
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_ordinary_sale_order_is_untouched(self):
        """أمر بيع عادي بلا حقول حجز: لا يفرض الموديول عليه شيئاً."""
        real = self.env['res.partner'].create({'name': 'عميل عادي'})
        order = self._order(partner_id=real.id)
        self.assertFalse(order.is_booking_order)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')


@tagged('post_install', '-at_install')
class TestBookingInvoice(AccountTestInvoicingCommon):
    """الفاتورة الضريبية المبسطة باسم المستأجر، والمتبقي لكل حجز.

    تقوم على تجهيزة أودو المحاسبية (AccountTestInvoicingCommon): تُنشئ
    دليل حسابات ودفاتر كاملة. قاعدة التطوير هنا بلا دليل، وبناؤه يدوياً
    في الاختبار ترك ثغرة حقيقية - الدفعة تُنشأ ولا تُطابَق مع الفاتورة
    فيبقى المتبقي كاملاً، فلا يختبر الاختبار ما كُتب له."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # تجهيزة أودو المحاسبية تعمل بمستخدم محاسبي بلا صلاحية مبيعات.
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_salesman')
        cls.cash = cls.env.ref('rental_booking.partner_rental_cash')
        cls.env.company.rental_cash_partner_id = cls.cash.id
        cls.product = cls.env['product.product'].create({
            'name': 'ليلة شاليه', 'type': 'service', 'list_price': 1300.0,
            'invoice_policy': 'order',
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })

    def _confirmed_order(self, **vals):
        order = self.env['sale.order'].create(dict({
            'partner_id': self.cash.id,
            'booking_source': 'direct',
            'booking_collected_by': 'cash',
            'guest_name': 'خلود علي الخليفي',
            'guest_id_number': '1032509497',
            'guest_mobile': '0500192440',
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})],
        }, **vals))
        order.action_confirm()
        return order

    def _invoice(self, order):
        return order._create_invoices()

    def _register_payment(self, invoice, amount):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'amount': amount}).action_create_payments()

    def _render(self, invoice):
        return self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice', invoice.ids)[0].decode()

    def _due_invoices(self):
        # domain على الإجراء نص في أودو 19 - يُحوَّل قبل البحث.
        action = self.env.ref('rental_booking.action_booking_amount_due')
        return self.env['account.move'].search(literal_eval(action.domain))

    # ---- نقل بيانات المستأجر ----
    def test_guest_details_reach_the_invoice(self):
        invoice = self._invoice(self._confirmed_order())
        self.assertEqual(invoice.guest_name, 'خلود علي الخليفي')
        self.assertEqual(invoice.guest_id_number, '1032509497')
        self.assertEqual(invoice.guest_mobile, '0500192440')

    def test_accounting_customer_stays_the_cash_partner(self):
        """الذمم والتقارير تبقى على العميل النقدي - الاسم للطباعة فقط."""
        self.assertEqual(self._invoice(self._confirmed_order()).partner_id, self.cash)

    def test_booking_reference_reaches_the_invoice(self):
        """في حقله الخاص - و"المرجع" يبقى اسم أمر البيع كما تملؤه أودو
        (S00892 في نموذج العميل)، فلا ينقلب سلوك قائم."""
        order = self._confirmed_order(booking_source='platform',
                                      booking_collected_by='platform',
                                      booking_reference='GT-7788')
        invoice = self._invoice(order)
        self.assertEqual(invoice.booking_reference, 'GT-7788')
        self.assertEqual(invoice.ref, order.name)

    # ---- الطباعة ----
    def test_printed_invoice_shows_the_guest_not_the_cash_partner(self):
        html = self._render(self._invoice(self._confirmed_order()))
        self.assertIn('خلود علي الخليفي', html, 'اسم المستأجر لا يظهر على الفاتورة')
        self.assertIn('1032509497', html, 'رقم الهوية لا يظهر')
        self.assertIn('0500192440', html, 'رقم الجوال لا يظهر')
        self.assertNotIn('عميل نقدي', html,
                         'اسم "عميل نقدي" ظهر على فاتورة المستأجر')

    def test_company_invoice_is_untouched(self):
        """فاتورة ضريبية كاملة لشركة: بلا بيانات مستأجر، فتبقى بعنوان
        جهة اتصالها كما هي."""
        company_partner = self.env['res.partner'].create({
            'name': 'شركة مستأجرة', 'vat': '311111111111113',
            'company_type': 'company'})
        order = self.env['sale.order'].create({
            'partner_id': company_partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        self.assertFalse(invoice.guest_name)
        self.assertIn('شركة مستأجرة', self._render(invoice))

    # ---- المبالغ المتبقية ----
    def test_partial_payment_leaves_a_tracked_balance(self):
        """المتبقي يُحسب لكل فاتورة على حدة، فيعمل رغم أن العميل مشترك."""
        order = self._confirmed_order()
        invoice = self._invoice(order)
        invoice.action_post()
        total = invoice.amount_total          # شامل الضريبة كما في الواقع
        self.assertGreater(total, 0.0)

        self._register_payment(invoice, 500.0)

        self.assertAlmostEqual(invoice.amount_residual, total - 500.0, places=2)
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertAlmostEqual(order.booking_amount_due, total - 500.0, places=2,
                               msg='المتبقي لا يظهر على شاشة الحجز')

    def test_two_guests_balances_do_not_mix(self):
        """أهم فحص: عميلهما المحاسبي واحد - فيجب أن يبقى متبقي كل حجز
        مستقلاً عن الآخر."""
        first = self._invoice(self._confirmed_order(guest_name='نزيل أول'))
        second = self._invoice(self._confirmed_order(guest_name='نزيل ثانٍ'))
        (first + second).action_post()
        self.assertEqual(first.partner_id, second.partner_id)

        second_total = second.amount_total
        self._register_payment(first, first.amount_total)

        self.assertEqual(first.amount_residual, 0.0)
        self.assertAlmostEqual(second.amount_residual, second_total, places=2,
                               msg='سداد نزيل أثّر على رصيد نزيل آخر')

    def test_due_screen_lists_only_unpaid_bookings(self):
        paid = self._invoice(self._confirmed_order(guest_name='نزيل سدّد'))
        unpaid = self._invoice(self._confirmed_order(guest_name='نزيل متبقٍ'))
        (paid + unpaid).action_post()
        self._register_payment(paid, paid.amount_total)

        listed = self._due_invoices()
        self.assertIn(unpaid, listed)
        self.assertNotIn(paid, listed)

    def test_due_screen_ignores_ordinary_invoices(self):
        """فاتورة بلا مستأجر (شركة مثلاً) ليست من شأن هذه الشاشة."""
        partner = self.env['res.partner'].create({'name': 'شركة أخرى'})
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 1,
                                         'price_unit': 100.0})],
        })
        invoice.action_post()
        self.assertNotIn(invoice, self._due_invoices())
