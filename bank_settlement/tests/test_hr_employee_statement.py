# -*- coding: utf-8 -*-
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

    def _create_dues_move(self, state, debit=0.0, credit=100.0):
        move = self.env['account.move'].create({
            'journal_id': self.journal.id,
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
