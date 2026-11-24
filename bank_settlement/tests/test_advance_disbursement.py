# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAdvanceDisbursement(TransactionCase):
    """صرف السلفة على دفعات.

    الحالة كما وصفها المستخدم: سلفة 1500 يُحوَّل منها 500 الآن والباقي
    بضغطة ثانية - وقد يكون التحويلان في اليوم نفسه (جزء مع الراتب وجزء
    منفصلاً)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # superuser ليس عضواً في مجموعات السداد البنكي.
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف الصرف الجزئي'})
        cls.reason = cls.env.ref('bank_settlement.advance_reason_salary_advance')
        cls.dues_account = cls.env['account.account'].create({
            'name': 'ذمم موظفين (اختبار صرف)', 'code': 'DSB211201',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'بنك الصرف', 'code': 'DSBB', 'type': 'bank',
                'company_id': cls.company.id,
            })

    # ------------------------------------------------------------------
    def _approved_advance(self, amount=1500.0):
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': amount,
            'payment_method': 'stc_pay', 'stc_number': '0501234567',
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        advance.action_confirm()
        advance.write({
            'journal_id': self.journal.id,
            'linked_account_id': self.dues_account.id,
        })
        return advance

    def _wizard(self, advance, mode, amount=None):
        wizard = self.env['bank.settlement.advance.disbursement.wizard'].with_context(
            default_advance_id=advance.id,
        ).create({'advance_id': advance.id, 'mode': mode,
                  'amount': amount if amount is not None else advance.undisbursed_amount})
        wizard.action_confirm()
        return wizard

    # ------------------------------------------------------------------
    def test_full_disbursement_behaves_exactly_as_before(self):
        """الضابط الموجب: الحالة الشائعة لم تتغيّر - قيد واحد وحالة
        "تم الصرف"، وmove_id مضبوط كما كان."""
        advance = self._approved_advance()
        advance.action_done()
        self.assertEqual(advance.state, 'paid')
        self.assertTrue(advance.move_id, 'لم يُنشأ القيد المحاسبي')
        self.assertEqual(advance.disbursed_amount, 1500.0)
        self.assertEqual(advance.undisbursed_amount, 0.0)
        self.assertFalse(advance.is_partially_disbursed)
        debit = advance.move_id.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(debit.debit, 1500.0, 'القيد لا يحمل كامل المبلغ')

    def test_partial_then_rest(self):
        """1500: تُصرف 500 ثم الباقي - الحالة التي طلبها."""
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)

        self.assertEqual(advance.disbursed_amount, 500.0)
        self.assertEqual(advance.undisbursed_amount, 1000.0)
        self.assertTrue(advance.is_partially_disbursed)
        self.assertEqual(
            advance.state, 'approved',
            'أُقفلت السلفة رغم أن جزءاً منها لم يُصرف - لن يظهر زر الصرف')
        self.assertEqual(
            advance.move_id.line_ids.filtered(lambda l: l.debit).debit, 500.0,
            'القيد الأول يحمل كامل المبلغ لا ما حُوِّل فعلاً')

        # الضغطة الثانية: الباقي
        self._wizard(advance, 'full')
        self.assertEqual(advance.disbursed_amount, 1500.0)
        self.assertEqual(advance.undisbursed_amount, 0.0)
        self.assertEqual(advance.state, 'paid', 'لم تُقفل السلفة بعد اكتمال الصرف')
        self.assertFalse(advance.is_partially_disbursed)

        lines = advance.disbursement_ids.filtered(lambda d: d.state == 'posted')
        self.assertEqual(len(lines), 2, 'لم تُسجَّل الدفعتان منفصلتين')
        self.assertEqual(sorted(lines.mapped('amount')), [500.0, 1000.0])
        self.assertEqual(
            len(set(lines.mapped('move_id').ids)), 2,
            'الدفعتان تشتركان في قيد واحد - لا تُطابَق كل حوالة على حدة')
        total = sum(
            sum(move.line_ids.filtered(lambda l: l.debit).mapped('debit'))
            for move in lines.mapped('move_id'))
        self.assertEqual(total, 1500.0, 'مجموع القيود لا يساوي مبلغ السلفة')

    def test_view_move_opens_every_entry_after_several_payments(self):
        """سلفة 2000 صُرفت 500 ثم 1500: زر "القيد المحاسبي" كان يفتح
        قيد الـ500 وحده، فتبدو السلفة مصروفة بـ500 لا بـ2000."""
        advance = self._approved_advance(amount=2000.0)
        self._wizard(advance, 'partial', 500.0)
        self._wizard(advance, 'full')
        self.assertEqual(advance.state, 'paid')
        self.assertEqual(advance.disbursement_count, 2)

        action = advance.action_view_move()
        self.assertEqual(
            action.get('res_model'), 'account.move',
            'الزر لا يفتح القيود')
        self.assertNotIn(
            'res_id', action,
            'الزر ما زال يفتح قيداً واحداً من قيدين')
        opened = self.env['account.move'].search(action['domain'])
        self.assertEqual(len(opened), 2, 'لم تُفتح قيود الدفعتين معاً')
        self.assertEqual(
            sum(opened.mapped(lambda m: sum(
                m.line_ids.filtered(lambda l: l.debit).mapped('debit')))),
            2000.0, 'مجموع القيود المفتوحة لا يساوي مبلغ السلفة')

    def test_view_move_still_opens_the_single_entry(self):
        """الضابط المقابل: الصرف بدفعة واحدة يفتح قيده مباشرةً كما كان."""
        advance = self._approved_advance()
        advance.action_done()
        action = advance.action_view_move()
        self.assertEqual(action.get('res_id'), advance.move_id.id)

    def test_two_partials_on_the_same_day(self):
        """جزء كراتب وجزء كسلفة في اليوم نفسه - حالة صرّح بها المستخدم."""
        advance = self._approved_advance()
        today = advance.transfer_date or self.env.cr.now().date()
        self._wizard(advance, 'partial', 500.0)
        advance.disbursement_ids.with_context(
            bank_settlement_disbursement_internal=True).write({'date': today})
        self._wizard(advance, 'partial', 1000.0)
        self.assertEqual(advance.state, 'paid')
        self.assertEqual(len(advance.disbursement_ids), 2)

    def test_three_partials_sum_to_the_total(self):
        advance = self._approved_advance(amount=900.0)
        self._wizard(advance, 'partial', 300.0)
        self._wizard(advance, 'partial', 300.0)
        self.assertEqual(advance.state, 'approved')
        self._wizard(advance, 'partial', 300.0)
        self.assertEqual(advance.state, 'paid')
        self.assertEqual(advance.disbursed_amount, 900.0)

    # ------------------------------------------------------------------
    def test_cannot_disburse_more_than_approved(self):
        """الضابط المقابل: الصرف الجزئي لا يفتح باباً لصرف ما لم يُعتمد."""
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)
        with self.assertRaises(UserError):
            self._wizard(advance, 'partial', 1100.0)

    def test_exact_remaining_is_allowed(self):
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)
        self._wizard(advance, 'partial', 1000.0)
        self.assertEqual(advance.undisbursed_amount, 0.0)

    def test_zero_or_negative_is_refused(self):
        advance = self._approved_advance()
        with self.assertRaises(UserError):
            advance.action_disburse(0.0)
        with self.assertRaises(UserError):
            advance.action_disburse(-100.0)

    def test_cannot_disburse_before_approval(self):
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': 500.0,
        })
        with self.assertRaises(UserError):
            advance.action_disburse(100.0)

    def test_posted_disbursement_cannot_be_edited_or_deleted(self):
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)
        line = advance.disbursement_ids[0]
        with self.assertRaises(UserError):
            line.amount = 600.0
        with self.assertRaises(UserError):
            line.unlink()

    def test_wizard_full_mode_ignores_a_typed_amount(self):
        """"كامل المتاح" يصرف المتاح مهما كُتب في خانة المبلغ."""
        advance = self._approved_advance()
        self._wizard(advance, 'full', 10.0)
        self.assertEqual(advance.disbursed_amount, 1500.0)
        self.assertEqual(advance.state, 'paid')

    # ------------------------------------------------------------------
    def test_reverse_unwinds_every_disbursement(self):
        """عكس سلفة صُرفت على دفعتين يجب أن يعكس القيدين معاً."""
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)
        self._wizard(advance, 'partial', 1000.0)
        moves = advance.disbursement_ids.mapped('move_id')
        self.assertEqual(len(moves), 2)

        advance.action_reverse_and_correct(reason='تصحيح')
        for move in moves:
            reverse = self.env['account.move'].search(
                [('reversed_entry_id', '=', move.id)])
            self.assertTrue(
                reverse, 'بقي قيد صرف بلا عكس - مال مصروف لسلفة أُلغي تنفيذها')
        self.assertFalse(
            advance.disbursement_ids.filtered(lambda d: d.state == 'posted'),
            'بقيت دفعات صرف قائمة بعد إلغاء التنفيذ')
        self.assertEqual(advance.disbursed_amount, 0.0)

    def test_return_for_correction_refused_after_several_disbursements(self):
        """الإرجاع للتصحيح يعيد قيداً واحداً لمسودة - لا معنى له مع عدة
        قيود، فيُمنع بنص واضح بدل أن يترك البقية مرحَّلة."""
        advance = self._approved_advance()
        self._wizard(advance, 'partial', 500.0)
        self._wizard(advance, 'partial', 1000.0)
        with self.assertRaises(UserError):
            advance._unpost_settlement_move()

    def test_prepaid_advance_cannot_be_split(self):
        """جدول الدفعة المقدمة يُبنى من كامل المبلغ وقت الصرف."""
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': 1500.0,
            'payment_method': 'stc_pay', 'stc_number': '0501234567',
            'is_prepaid': True, 'prepaid_days': 30,
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        advance.action_confirm()
        advance.write({
            'journal_id': self.journal.id,
            'linked_account_id': self.dues_account.id,
        })
        self.assertTrue(advance.is_prepaid, 'افتراض الاختبار سقط')
        with self.assertRaises(UserError):
            advance.action_disburse(500.0)
