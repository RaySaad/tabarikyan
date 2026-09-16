# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
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
