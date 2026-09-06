# -*- coding: utf-8 -*-
from datetime import date

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrEmployeeStatement(TransactionCase):
    """كشف حساب الموظف (hr_employee.py: _get_employee_statement_data) -
    يتحقق تحديداً من قسم قيود حساب "ذمم الموظفين" (212003)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف - كشف حساب'})
        # work_contact_id يُنشأ تلقائياً عند إنشاء الموظف (انظر hr/models/
        # hr_employee.py) - لا حاجة لإنشائه يدوياً.
        cls.partner = cls.employee.work_contact_id
        cls.dues_account = cls.env['account.account'].search(
            [('code', '=', '212003')], limit=1,
        )
        if not cls.dues_account:
            cls.dues_account = cls.env['account.account'].create({
                'code': '212003',
                'name': 'ذمم الموظفين',
                'account_type': 'liability_current',
            })
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cls.env.company.id)], limit=1,
        )

    def _create_dues_move(self, state, debit=0.0, credit=100.0, move_date=False):
        move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': move_date or fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'account_id': self.dues_account.id,
                    'partner_id': self.partner.id,
                    'debit': debit,
                    'credit': credit,
                    'name': 'اختبار كشف حساب',
                }),
                (0, 0, {
                    'account_id': self.env['account.account'].search(
                        [('id', '!=', self.dues_account.id)], limit=1,
                    ).id,
                    'debit': credit,
                    'credit': debit,
                    'name': 'اختبار كشف حساب - موازنة',
                }),
            ],
        })
        if state == 'posted':
            move.action_post()
        return move

    def test_statement_includes_draft_dues_entries(self):
        """ثغرة حقيقية: القسم كان يقتصر على القيود المرحّلة فقط
        (move_id.state == 'posted') - طلب صريح: يجب أن يفحص حتى القيود
        غير المرحّلة (لا تزال مسودة)."""
        self._create_dues_move('draft', credit=150.0)

        data = self.employee._get_employee_statement_data()

        self.assertTrue(
            any(line['credit'] == 150.0 for line in data['lines']),
            'القيد غير المرحّل (مسودة) يجب أن يظهر في كشف الحساب',
        )

    def test_statement_still_excludes_cancelled_dues_entries(self):
        """القيود الملغاة (cancel) تبقى مستبعدة - لا معنى لعرضها ضمن
        ذمم الموظف."""
        move = self._create_dues_move('draft', credit=250.0)
        move.button_cancel()

        data = self.employee._get_employee_statement_data()

        self.assertFalse(
            any(line['credit'] == 250.0 for line in data['lines']),
            'القيد الملغى يجب ألا يظهر في كشف الحساب',
        )

    def test_statement_includes_posted_dues_entries(self):
        """القيود المرحّلة تبقى تظهر كما كانت دائماً."""
        self._create_dues_move('posted', credit=350.0)

        data = self.employee._get_employee_statement_data()

        self.assertTrue(
            any(line['credit'] == 350.0 for line in data['lines']),
            'القيد المرحّل يجب أن يبقى ظاهراً في كشف الحساب',
        )

    def test_date_from_excludes_earlier_entries(self):
        """طلب صريح: شاشة اختيار الموظف وفترة الكشف (من بداية العقد أو
        تاريخ محدد) - date_from يجب أن يستبعد الحركات السابقة له."""
        self._create_dues_move('posted', credit=500.0, move_date=date(2020, 1, 1))

        data = self.employee._get_employee_statement_data(date_from=date(2024, 1, 1))

        self.assertFalse(
            any(line['credit'] == 500.0 for line in data['lines']),
            'حركة قبل date_from يجب ألا تظهر في الكشف',
        )

    def test_date_to_excludes_later_entries(self):
        self._create_dues_move('posted', credit=600.0, move_date=date(2026, 12, 31))

        data = self.employee._get_employee_statement_data(date_to=date(2026, 6, 1))

        self.assertFalse(
            any(line['credit'] == 600.0 for line in data['lines']),
            'حركة بعد date_to يجب ألا تظهر في الكشف',
        )

    def test_date_range_includes_entries_within_bounds(self):
        self._create_dues_move('posted', credit=700.0, move_date=date(2026, 3, 15))

        data = self.employee._get_employee_statement_data(
            date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
        )

        self.assertTrue(
            any(line['credit'] == 700.0 for line in data['lines']),
            'حركة ضمن الفترة المحدَّدة يجب أن تظهر في الكشف',
        )

    def test_no_date_range_shows_all_history(self):
        """بلا date_from/date_to (السلوك الأصلي) - كل الحركة التاريخية
        تظهر، بغض النظر عن تاريخها."""
        self._create_dues_move('posted', credit=800.0, move_date=date(2015, 1, 1))

        data = self.employee._get_employee_statement_data()

        self.assertTrue(
            any(line['credit'] == 800.0 for line in data['lines']),
            'بلا فترة محدَّدة، كل الحركة التاريخية يجب أن تظهر',
        )

    # ------------------------------------------------------------------
    # اصطلاح إشارة الصافي (طلب صريح): من منظور الشركة لا الموظف.
    # هذه الاختبارات تتعمّد الاعتماد على السلف/التصفيات وحدها (لا تحتاج
    # دفتر يومية ولا حسابات) حتى تبقى صالحة في أي قاعدة اختبار.
    # ------------------------------------------------------------------
    def _advance(self, amount):
        """سلفة = مدين (على الموظف - تُخصم من راتبه لاحقاً)."""
        reason = self.env['bank.settlement.advance.reason'].search([], limit=1)             or self.env['bank.settlement.advance.reason'].create({'name': 'سبب اختبار'})
        return self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': reason.id,
            'amount': amount,
        })

    def _settlement(self, amount):
        """تصفية مندوب = دائن (للموظف)."""
        return self.env['bank.settlement.representative'].create({
            'employee_id': self.employee.id,
            'date': date(2026, 1, 1),
            'settlement_amount': amount,
        })

    def test_net_total_is_positive_when_employee_owes_company(self):
        self._advance(1000.0)
        self._settlement(300.0)
        data = self.employee._get_employee_statement_data()
        self.assertAlmostEqual(data['total_debit'], 1000.0, places=2)
        self.assertAlmostEqual(data['total_credit'], 300.0, places=2)
        self.assertAlmostEqual(data['net_total'], 700.0, places=2)

    def test_net_total_is_negative_when_company_owes_employee(self):
        self._advance(300.0)
        self._settlement(1000.0)
        data = self.employee._get_employee_statement_data()
        self.assertAlmostEqual(data['net_total'], -700.0, places=2)

    def test_net_total_is_zero_when_balanced(self):
        self._advance(500.0)
        self._settlement(500.0)
        data = self.employee._get_employee_statement_data()
        self.assertAlmostEqual(data['net_total'], 0.0, places=2)
