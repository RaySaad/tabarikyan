# -*- coding: utf-8 -*-
from ast import literal_eval
from unittest.mock import patch

from odoo import fields
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

    # ---- الشاشة ----
    def test_guest_fields_have_a_place_on_the_booking_screen(self):
        """كل بيان يُطبع على الفاتورة المبسطة يلزمه حقل يُكتب فيه.

        رقم هوية المستأجر كان معرَّفاً في النموذج ويُطبع على الفاتورة
        والعقد، بلا حقل في شاشة الحجز - فلا سبيل لإدخاله."""
        arch = self.env['sale.order'].get_view(
            self.env.ref('sale.view_order_form').id, 'form')['arch']
        for field in ('guest_name', 'guest_id_number', 'guest_mobile'):
            self.assertIn('name="%s"' % field, arch,
                          'الحقل %s لا يظهر في شاشة الحجز' % field)

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

@tagged('post_install', '-at_install')
class TestBookingPayments(AccountTestInvoicingCommon):
    """دفعات تُسجَّل على الحجز بتواريخها، وتنعكس على الفاتورة عند صدورها."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_salesman')
        cls.cash = cls.env.ref('rental_booking.partner_rental_cash')
        cls.env.company.rental_cash_partner_id = cls.cash.id
        cls.product = cls.env['product.product'].create({
            'name': 'ليلة شاليه', 'type': 'service', 'list_price': 1000.0,
            'invoice_policy': 'order',
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })
        cls.journal = cls.company_data['default_journal_cash']
        # دفعة أودو 19 لا تُنتج قيداً إلا بحساب مقبوضات معلّقة على طريقة
        # الدفع - تضبطه قوالب دليل الحسابات في الواقع، ونضبطه هنا.
        outstanding = cls.env['account.account'].create({
            'name': 'مقبوضات معلّقة', 'code': 'TOUTS1',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [(6, 0, cls.env.company.ids)]})
        cls.journal.inbound_payment_method_line_ids[:1].payment_account_id = outstanding.id

    def _order(self):
        order = self.env['sale.order'].create({
            'partner_id': self.cash.id,
            'booking_source': 'direct',
            'booking_collected_by': 'cash',
            'guest_name': 'مستأجر الدفعات',
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})],
        })
        order.action_confirm()
        return order

    def _pay(self, order, amount, date):
        self.env['rental.booking.payment.register'].with_context(
            default_order_id=order.id,
        ).create({
            'order_id': order.id, 'amount': amount,
            'payment_date': date, 'journal_id': self.journal.id,
        }).action_register()

    def test_payment_is_posted_on_its_own_date(self):
        """يُرحَّل فوراً بتاريخه - لا يُؤجَّل للفوترة، فرصيد الصندوق صحيح
        لحظة بلحظة ولا يفشل لو أُقفلت الفترة لاحقاً."""
        order = self._order()
        self._pay(order, 500.0, '2026-09-12')

        payment = order.booking_payment_ids
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.date, fields.Date.to_date('2026-09-12'))
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(payment.booking_order_id, order)

    def test_two_payments_show_paid_and_due_before_invoicing(self):
        order = self._order()
        total = order.amount_total
        self._pay(order, 500.0, '2026-09-12')
        self.assertAlmostEqual(order.booking_amount_paid, 500.0, places=2)
        self.assertAlmostEqual(order.booking_amount_due, total - 500.0, places=2)

        self._pay(order, 300.0, '2026-09-14')
        self.assertAlmostEqual(order.booking_amount_paid, 800.0, places=2)
        self.assertAlmostEqual(order.booking_amount_due, total - 800.0, places=2)

    def test_payments_reflect_on_the_invoice_when_it_is_issued(self):
        """جوهر الطلب: الدفعات تُسجَّل على الحجز أولاً، فتظهر الفاتورة
        مسدَّدة بها فور ترحيلها - كفاتورة العميل النموذجية."""
        order = self._order()
        total = order.amount_total
        self._pay(order, 500.0, '2026-09-12')
        self._pay(order, total - 500.0, '2026-09-14')

        invoice = order._create_invoices()
        invoice.action_post()

        # in_payment حالة صحيحة أيضاً: المبلغ مطابَق لكنه في حساب
        # "المقبوضات المعلّقة" حتى يُؤكَّد في كشف البنك. المهم أن المتبقي صفر.
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'),
                      'الدفعات المسجَّلة على الحجز لم تنعكس على الفاتورة')
        self.assertEqual(invoice.amount_residual, 0.0)
        self.assertAlmostEqual(order.booking_amount_due, 0.0, places=2)

    def test_partial_payments_leave_the_invoice_partially_paid(self):
        order = self._order()
        total = order.amount_total
        self._pay(order, 500.0, '2026-09-12')

        invoice = order._create_invoices()
        invoice.action_post()

        self.assertEqual(invoice.payment_state, 'partial')
        self.assertAlmostEqual(invoice.amount_residual, total - 500.0, places=2)

    def test_payment_after_the_invoice_is_reconciled_immediately(self):
        """الترتيب الآخر: الفاتورة صدرت أولاً ثم دفع النزيل."""
        order = self._order()
        total = order.amount_total
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertEqual(invoice.payment_state, 'not_paid')

        self._pay(order, total, '2026-09-14')

        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertEqual(invoice.amount_residual, 0.0)

    def test_one_guest_payment_never_lands_on_another_booking(self):
        """العميل المحاسبي واحد لكل النزلاء - والدفعة مربوطة بحجزها، فلا
        تُطابَق مع فاتورة حجز آخر."""
        first, second = self._order(), self._order()
        first_invoice = first._create_invoices()
        second_invoice = second._create_invoices()
        (first_invoice + second_invoice).action_post()

        self._pay(first, first.amount_total, '2026-09-12')

        self.assertEqual(first_invoice.amount_residual, 0.0)
        self.assertEqual(second_invoice.payment_state, 'not_paid',
                         'دفعة حجز طُبّقت على فاتورة حجز آخر')
        self.assertEqual(second_invoice.amount_residual, second.amount_total)

    def test_payment_company_follows_the_booking_not_the_journal(self):
        """الحالة التي ظهرت عندهم: دفاتر الدفع على الشركة الأم والحجز على
        فرع ("منتجع سحابة سما"). بلا تحديد الشركة صراحةً تحسبها أودو من
        الدفتر، فتخرج الدفعة على شركة وقيدها على أخرى وترفضها أودو:
        "لا يُسمح بأي تداخل بين الشركات"."""
        branch = self.env['res.company'].create({
            'name': 'منتجع فرعي', 'parent_id': self.env.company.id})
        self.env.user.company_ids |= branch
        # الفرع في الواقع يرث دليل حسابات الأم عند إنشائه (precommit)، وهذا
        # لا يجري داخل الاختبار، فنضبط ذمم العميل للفرع يدوياً.
        self.cash.with_company(branch).property_account_receivable_id =             self.company_data['default_account_receivable']
        order = self._order()
        order.company_id = branch.id
        self.assertEqual(self.journal.company_id, branch.parent_id,
                         'الدفتر ليس على الشركة الأم - الاختبار لا يفحص الحالة')

        self._pay(order, 100.0, '2026-09-16')

        payment = order.booking_payment_ids
        self.assertEqual(payment.company_id, branch,
                         'شركة الدفعة تبعت الدفتر لا الحجز')
        self.assertEqual(payment.move_id.company_id, payment.company_id,
                         'قيد الدفعة على شركة غير شركة الدفعة')

    def test_journals_of_the_parent_company_are_offered_to_a_branch(self):
        """الحالة التي ظهرت عند المستخدم: الحجز على فرع ودفاتر الصندوق
        على الشركة الأم - فكانت قائمة "طريقة الدفع" فارغة تماماً."""
        branch = self.env['res.company'].create({
            'name': 'فرع الشاليهات', 'parent_id': self.env.company.id})
        Wizard = self.env['rental.booking.payment.register']

        journals = self.env['account.journal'].search(
            Wizard._eligible_journal_domain(branch))

        self.assertIn(self.journal, journals,
                      'دفاتر الشركة الأم لا تظهر لحجز على فرع')

    def test_strict_company_match_would_have_been_empty(self):
        """يثبت أن سبب الفراغ هو المطابقة الصارمة لا غياب الدفاتر."""
        branch = self.env['res.company'].create({
            'name': 'فرع آخر', 'parent_id': self.env.company.id})
        strict = self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')), ('company_id', '=', branch.id)])
        self.assertFalse(strict)

    def test_missing_journal_gives_a_clear_message(self):
        """بدل قائمة فارغة صامتة."""
        order = self._order()
        with patch.object(
            type(self.env['account.journal']), 'search_count', return_value=0
        ):
            with self.assertRaises(UserError):
                order.action_register_booking_payment()

    def test_zero_amount_is_rejected(self):
        order = self._order()
        with self.assertRaises(UserError):
            self._pay(order, 0.0, '2026-09-12')

@tagged('post_install', '-at_install')
class TestRentalContract(AccountTestInvoicingCommon):
    """عقد الإيجار: يُطبع ويُرسل بعد تأكيد الحجز وقبض العربون."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_salesman')
        cls.cash = cls.env.ref('rental_booking.partner_rental_cash')
        cls.env.company.rental_cash_partner_id = cls.cash.id
        cls.env.company.rental_contract_terms = (
            '<p>التأمين 300 ريال يُسترجع عند المغادرة.</p>')
        cls.product = cls.env['product.product'].create({
            'name': 'القسم رقم 3', 'type': 'service', 'list_price': 1000.0,
            'invoice_policy': 'order',
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })
        cls.journal = cls.company_data['default_journal_cash']
        outstanding = cls.env['account.account'].create({
            'name': 'مقبوضات معلّقة عقد', 'code': 'TOUTC1',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [(6, 0, cls.env.company.ids)]})
        cls.journal.inbound_payment_method_line_ids[:1].payment_account_id = outstanding.id

    def _booking(self, confirm=True, **vals):
        order = self.env['sale.order'].create(dict({
            'partner_id': self.cash.id,
            'booking_source': 'direct',
            'booking_collected_by': 'cash',
            'guest_name': 'خلود علي الخليفي',
            'guest_id_number': '1032509497',
            'guest_mobile': '0500192440',
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})],
        }, **vals))
        if confirm:
            order.action_confirm()
        return order

    def _pay(self, order, amount):
        self.env['rental.booking.payment.register'].create({
            'order_id': order.id, 'amount': amount,
            'payment_date': fields.Date.context_today(order),
            'journal_id': self.journal.id,
        }).action_register()

    def _render_contract(self, order):
        return self.env['ir.actions.report']._render_qweb_html(
            'rental_booking.report_rental_contract', order.ids)[0].decode()

    # ---- شروط الإرسال ----
    def test_contract_blocked_before_confirmation(self):
        order = self._booking(confirm=False)
        with self.assertRaises(UserError):
            order.action_print_rental_contract()

    def test_contract_blocked_before_any_payment(self):
        """عقد بلا عربون مقبوض = التزام بلا مقابل."""
        order = self._booking()
        self.assertEqual(order.booking_amount_paid, 0.0)
        with self.assertRaises(UserError):
            order.action_print_rental_contract()

    def test_contract_shows_parties_amounts_and_terms(self):
        order = self._booking()
        self._pay(order, 500.0)
        html = self._render_contract(order)

        self.assertIn('عقد إيجار', html)
        self.assertIn('خلود علي الخليفي', html)
        self.assertIn('1032509497', html)
        self.assertIn('القسم رقم 3', html)
        self.assertIn('التأمين 300 ريال', html, 'بنود العقد لا تظهر')

    def test_contract_has_no_signatures_and_no_payments_table(self):
        """طلب صريح: مستند شكلي بسيط للمستأجر - المبالغ ومدة الحجز فقط.
        تفصيل الدفعات موضعه الفاتورة."""
        order = self._booking()
        self._pay(order, 500.0)
        html = self._render_contract(order)

        self.assertNotIn('التوقيع', html, 'خانات التوقيع ما زالت في العقد')
        self.assertNotIn('الدفعات المستلمة', html, 'جدول الدفعات ما زال في العقد')
        self.assertIn('المدفوع', html)
        self.assertIn('المتبقي', html)

    def test_booking_period_is_shown_when_available(self):
        """مدة الحجز تأتي من حقول تطبيق التأجير (نسخة مدفوعة) - تُقرأ
        بأمان، فالموديول لا يعتمد عليه وقد لا تكون موجودة."""
        order = self._booking()
        period = order._get_booking_period()
        self.assertIn('nights', period)
        if 'rental_start_date' not in order._fields:
            self.assertFalse(period['start'])
            self.assertEqual(period['nights'], 0)

    def test_printing_follows_the_same_conditions(self):
        order = self._booking()
        with self.assertRaises(UserError):
            order.action_print_rental_contract()
        self._pay(order, 500.0)
        self.assertTrue(order.action_print_rental_contract())
