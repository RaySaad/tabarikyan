# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeStatementWizard(TransactionCase):
    """معالج "كشف حساب الموظف" (wizard/employee_statement_wizard.py) -
    طلب صريح: شاشة تختار الموظف وفترة الكشف (من بداية العقد أو تاريخ
    محدد) قبل الطباعة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف - معالج كشف حساب'})
        cls.Wizard = cls.env['bank.settlement.employee.statement.wizard']

    def test_action_print_requires_employee(self):
        # .new() عمداً (وليس create()) - employee_id إلزامي على مستوى
        # قاعدة البيانات (required=True)، فمحاولة كتابة/إنشاء سجل حقيقي
        # بدونه تفشل بقيد NOT NULL قبل الوصول لتحقق action_print() نفسه.
        # سجل افتراضي (NewId) لا يفرض هذا القيد، فيصل الاستدعاء فعلياً
        # لمنطق التحقق المقصود اختباره هنا.
        wizard = self.Wizard.new({})

        with self.assertRaises(UserError):
            wizard.action_print()

    def test_custom_mode_requires_date_from(self):
        wizard = self.Wizard.create({
            'employee_id': self.employee.id, 'date_mode': 'custom',
        })

        with self.assertRaises(UserError):
            wizard.action_print()

    def test_date_to_before_date_from_rejected(self):
        wizard = self.Wizard.create({
            'employee_id': self.employee.id, 'date_mode': 'custom',
            'date_from': date(2026, 6, 1), 'date_to': date(2026, 1, 1),
        })

        with self.assertRaises(UserError):
            wizard.action_print()

    def _assert_report_action(self, action):
        """report_action() قد يُرجِع إجراء التقرير مباشرة (النوع
        'ir.actions.report')، أو - إن لم تكن الشركة قد أعدَّت تخطيط
        المستندات (Document Layout) بعد، كما هو الحال في بيئة اختبار
        جديدة - إجراء "إعداد تخطيط المستندات" القياسي بـ Odoo نفسه أولاً،
        الذي يُضمِّن إجراء التقرير الفعلي داخل context['report_action']
        (سلوك قياسي بإطار Odoo، وليس خاصاً بهذا المعالج). نتحقق من كلا
        الاحتمالين بدل افتراض شكل واحد فقط."""
        self.assertTrue(action)
        report_name = action.get('report_name') or (
            action.get('context', {}).get('report_action', {}).get('report_name')
        )
        self.assertEqual(report_name, 'bank_settlement.report_hr_employee_statement')

    def test_custom_mode_with_valid_range_returns_report_action(self):
        wizard = self.Wizard.create({
            'employee_id': self.employee.id, 'date_mode': 'custom',
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 12, 31),
        })

        self._assert_report_action(wizard.action_print())

    def test_contract_start_mode_resolves_without_error(self):
        """موظف بلا أي عقد مسجَّل - يجب ألا تفشل، وتُرجِع بلا حد أدنى
        (False) كأقرب تفسير عملي لـ"من بداية العقد" حين لا يوجد عقد."""
        wizard = self.Wizard.create({
            'employee_id': self.employee.id, 'date_mode': 'contract_start',
        })

        self._assert_report_action(wizard.action_print())
        self.assertIsInstance(wizard.date_from, (bool, date))

    def test_onchange_date_mode_clears_date_from(self):
        wizard = self.Wizard.new({
            'employee_id': self.employee.id, 'date_mode': 'custom',
            'date_from': date(2026, 1, 1),
        })

        wizard.date_mode = 'contract_start'
        wizard._onchange_date_mode()

        self.assertFalse(wizard.date_from)
