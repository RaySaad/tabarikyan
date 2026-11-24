# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAdvanceRepayment(TransactionCase):
    """السداد الجزئي للسلفة.

    القرار المحوري: "خصم من الراتب" بلا قيد محاسبي هنا - مسير الرواتب
    يقيّد الخصم أصلاً على حساب ذمم الموظفين (211201)، فالقيد الثاني
    يحتسبه مرتين."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # superuser ليس عضواً في مجموعات السداد البنكي - انظر الشرح
        # الكامل في test_bank_settlement_mixin.setUpClass.
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({'name': 'موظف الاسترداد'})
        cls.reason = cls.env.ref('bank_settlement.advance_reason_salary_advance')
        cls.dues_account = cls.env['account.account'].create({
            'name': 'ذمم موظفين (اختبار استرداد)', 'code': 'REP211201',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'بنك الاسترداد', 'code': 'REPB', 'type': 'bank',
                'company_id': cls.company.id,
            })
        cls.outstanding = cls.env['account.account'].create({
            'name': 'مقبوضات معلقة (اختبار)', 'code': 'REPOUT',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        # على *طريقة الدفع في الدفتر* لا على حساب التحويلات وحده: هو
        # أعلى مصدر في ترتيب أودو، فيصير الاختبار واحداً في قاعدة بلا
        # شجرة حسابات وفي قاعدة بشجرة. الاعتماد على transfer_account_id
        # وحده كان يمر محلياً ويفشل على قاعدة فيها شجرة (حيث يسبقه
        # حساب الشجرة) - وهو ما حمّر بناء Odoo.sh فعلياً.
        cls.company.transfer_account_id = cls.outstanding.id
        for line in cls.journal.inbound_payment_method_line_ids:
            line.payment_account_id = cls.outstanding.id

    # ------------------------------------------------------------------
    def _paid_advance(self, amount=1000.0):
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
        advance.action_done()
        self.assertEqual(advance.state, 'paid')
        return advance

    def _repay(self, advance, amount, method='salary_deduction', post=True):
        vals = {
            'advance_id': advance.id, 'amount': amount, 'method': method,
        }
        if method != 'salary_deduction':
            vals['journal_id'] = self.journal.id
        repayment = self.env['bank.settlement.advance.repayment'].create(vals)
        if post:
            repayment.action_post()
        return repayment

    # ------------------------------------------------------------------
    def test_advance_starts_fully_open(self):
        """الضابط الموجب: لولاه لمرّ "المتبقي صفر دائماً" على أنه نجاح."""
        advance = self._paid_advance()
        self.assertEqual(advance.repaid_amount, 0.0)
        self.assertEqual(advance.remaining_amount, 1000.0)
        self.assertEqual(advance.repayment_state, 'open')

    def test_partial_repayment_reduces_remaining(self):
        advance = self._paid_advance()
        self._repay(advance, 300.0)
        self.assertEqual(advance.repaid_amount, 300.0)
        self.assertEqual(advance.remaining_amount, 700.0,
                         'المتبقي لم ينقص بقيمة الدفعة')
        self.assertEqual(advance.repayment_state, 'partial')

    def test_full_repayment_settles(self):
        advance = self._paid_advance()
        self._repay(advance, 400.0)
        self._repay(advance, 600.0)
        self.assertEqual(advance.remaining_amount, 0.0)
        self.assertEqual(advance.repayment_state, 'settled')

    def test_draft_repayment_is_not_counted(self):
        """دفعة لم تُسجَّل بعد ليست سداداً - الضابط السالب للحساب."""
        advance = self._paid_advance()
        self._repay(advance, 250.0, post=False)
        self.assertEqual(advance.repaid_amount, 0.0)
        self.assertEqual(advance.repayment_state, 'open')

    # ------------------------------------------------------------------
    def test_salary_deduction_creates_no_move(self):
        """جوهر القرار: مسير الرواتب يقيّد الخصم، فالقيد هنا يحتسبه مرتين."""
        advance = self._paid_advance()
        repayment = self._repay(advance, 500.0, method='salary_deduction')
        self.assertFalse(
            repayment.move_id,
            'أُنشئ قيد لخصم من الراتب - يُحتسب الخصم مرتين على ذمة الموظف')
        self.assertEqual(repayment.state, 'posted')
        self.assertEqual(advance.remaining_amount, 500.0,
                         'الخصم لم يُحتسب في المتبقي رغم أنه متابعة فقط')

    def test_cash_repayment_creates_balanced_move(self):
        advance = self._paid_advance()
        repayment = self._repay(advance, 400.0, method='bank_transfer')
        move = repayment.move_id
        self.assertTrue(move, 'سداد نقدي بلا قيد محاسبي')
        self.assertEqual(move.state, 'posted')

        debit_line = move.line_ids.filtered(lambda l: l.debit)
        credit_line = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(
            credit_line.account_id, self.dues_account,
            'الاسترداد لم يُقفل نفس حساب السلفة - يبقى رصيدها قائماً')
        self.assertEqual(
            debit_line.account_id, self.outstanding,
            'المدين على حساب البنك مباشرة بدل المقبوضات المعلقة')
        self.assertEqual(debit_line.debit, 400.0)
        self.assertEqual(credit_line.credit, 400.0)

    def test_mixed_methods_on_one_advance(self):
        """سلفة 2000: 500 خصماً من الراتب و1500 تحويلاً - الحالة التي
        سألت عنها. الطريقة خاصية كل دفعة لا خاصية السلفة، فيُمزَج."""
        baseline_net = self.employee._get_employee_statement_data()['net_total']
        advance = self._paid_advance(amount=2000.0)
        deduction = self._repay(advance, 500.0, method='salary_deduction')
        transfer = self._repay(advance, 1500.0, method='bank_transfer')

        self.assertFalse(deduction.move_id,
                         'الخصم من الراتب أنشأ قيداً - يُحتسب مرتين')
        self.assertTrue(transfer.move_id, 'التحويل بلا قيد محاسبي')
        # القيد يحمل 1500 وحدها - لا مبلغ السلفة ولا المجموع.
        credit_line = transfer.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit_line.credit, 1500.0,
                         'قيد التحويل لا يحمل مبلغ دفعته وحدها')
        self.assertEqual(credit_line.account_id, self.dues_account)

        self.assertEqual(advance.repaid_amount, 2000.0)
        self.assertEqual(advance.remaining_amount, 0.0)
        self.assertEqual(advance.repayment_state, 'settled',
                         'السلفة لم تُقفل رغم سداد كامل مبلغها بطريقتين')

        # الكشف يعرض الدفعتين منفصلتين، وصافيه ينقص بمجموعهما.
        # فرقاً عن خط أساس لا قيمةً مطلقة: للموظف في قاعدة حقيقية حركة
        # أخرى على حساب الذمم، فتُفشل أي مقارنة برقم ثابت بلا عيب في
        # المنتج - وهذا بالضبط صنف الهشاشة الذي حمّر البناء.
        data = self.employee._get_employee_statement_data()
        credits = [l['credit'] for l in data['lines'] if l['credit']]
        self.assertIn(500.0, credits, 'دفعة الخصم من الراتب لا تظهر في الكشف')
        self.assertIn(1500.0, credits, 'دفعة التحويل لا تظهر في الكشف')
        self.assertAlmostEqual(
            data['net_total'], baseline_net, places=2,
            msg='صافي الكشف لم يعد لما كان عليه بعد سداد السلفة كاملةً')

    def test_mixed_methods_cannot_exceed_total(self):
        """الضابط المقابل: الخلط لا يفتح باباً لتجاوز مبلغ السلفة."""
        advance = self._paid_advance(amount=2000.0)
        self._repay(advance, 500.0, method='salary_deduction')
        self._repay(advance, 1500.0, method='bank_transfer')
        with self.assertRaises(ValidationError):
            self._repay(advance, 1.0, method='salary_deduction')

    # ------------------------------------------------------------------
    def test_exact_remaining_is_allowed(self):
        """الضابط المقابل لمنع التجاوز: المبلغ المساوي للمتبقي يمر."""
        advance = self._paid_advance()
        self._repay(advance, 600.0)
        self._repay(advance, 400.0)
        self.assertEqual(advance.remaining_amount, 0.0)

    def test_over_repayment_is_blocked(self):
        advance = self._paid_advance()
        self._repay(advance, 600.0)
        with self.assertRaises(ValidationError):
            self._repay(advance, 500.0)

    def test_zero_amount_is_blocked(self):
        advance = self._paid_advance()
        with self.assertRaises(ValidationError):
            self._repay(advance, 0.0)

    def test_repayment_before_disbursement_is_blocked(self):
        """لا دين قبل أن يخرج المال."""
        advance = self.env['bank.settlement.advance'].create({
            'employee_id': self.employee.id,
            'advance_reason_id': self.reason.id,
            'amount': 500.0,
        })
        repayment = self.env['bank.settlement.advance.repayment'].create({
            'advance_id': advance.id, 'amount': 100.0,
            'method': 'salary_deduction',
        })
        with self.assertRaises(UserError):
            repayment.action_post()

    def test_posted_repayment_cannot_be_edited_or_deleted(self):
        advance = self._paid_advance()
        repayment = self._repay(advance, 200.0)
        with self.assertRaises(UserError):
            repayment.amount = 300.0
        with self.assertRaises(UserError):
            repayment.unlink()

    # ------------------------------------------------------------------
    def test_cancel_restores_remaining_and_reverses_move(self):
        advance = self._paid_advance()
        repayment = self._repay(advance, 400.0, method='bank_transfer')
        move = repayment.move_id
        repayment.action_cancel()
        self.assertEqual(repayment.state, 'cancel')
        self.assertEqual(advance.remaining_amount, 1000.0,
                         'المتبقي لم يعد بعد إلغاء الدفعة')
        reverse = self.env['account.move'].search(
            [('reversed_entry_id', '=', move.id)])
        self.assertTrue(reverse, 'أُلغيت الدفعة وبقي قيدها في الدفاتر')

    def test_cannot_reverse_advance_with_posted_repayments(self):
        """عكس الصرف وحده يترك قيود الاسترداد بلا أصل."""
        advance = self._paid_advance()
        self._repay(advance, 300.0)
        with self.assertRaises(UserError):
            advance.action_reverse_and_correct(reason='تصحيح')

    # ------------------------------------------------------------------
    def test_statement_shows_repayment_as_credit(self):
        baseline_net = self.employee._get_employee_statement_data()['net_total']
        advance = self._paid_advance()
        self._repay(advance, 350.0)
        data = self.employee._get_employee_statement_data()
        credits = [l for l in data['lines'] if l['credit'] == 350.0]
        self.assertTrue(credits, 'السداد لا يظهر في كشف حساب الموظف')
        self.assertIn('سداد سلفة', credits[0]['description'])
        self.assertAlmostEqual(
            data['net_total'], baseline_net + 1000.0 - 350.0, places=2,
            msg='صافي الكشف لم ينقص بقيمة السداد')
