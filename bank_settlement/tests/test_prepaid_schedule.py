# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPrepaidSchedule(TransactionCase):
    """اختبارات "الدفعة المقدمة" - دقة التقسيم بالأيام، التوزيع التحليلي
    الديناميكي حسب منصة المندوب، التسوية التلقائية عند نقل المنصة،
    والمهمة المجدولة (لا ترحّل فترة قبل انتهائها)، بالإضافة للثغرات
    المُصلحة: إيقاف الجدول، قفل الإعدادات بعد التنفيذ، أسطر المبلغ
    الصفري، وحماية العملة."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Account = cls.env['account.account'].sudo()
        cls.prepaid_account = Account.create({
            'code': 'TST114001', 'name': 'مصروفات مدفوعة مقدماً - اختبار',
            'account_type': 'asset_current',
        })
        cls.expense_account = Account.create({
            'code': 'TST511001', 'name': 'مصروف اختبار', 'account_type': 'expense',
        })
        cls.bank_account = Account.create({
            'code': 'TST101001', 'name': 'بنك اختبار', 'account_type': 'asset_cash',
        })
        cls.journal = cls.env['account.journal'].sudo().search([], limit=1)
        if not cls.journal.default_account_id:
            cls.journal.default_account_id = cls.bank_account.id
        cls.category = cls.env['bank.settlement.prepaid.category'].sudo().create({
            'name': 'كرت عمل - اختبار',
            'prepaid_account_id': cls.prepaid_account.id,
            'expense_account_id': cls.expense_account.id,
            'journal_id': cls.journal.id,
        })

        plan = cls.env['account.analytic.plan'].sudo().search([], limit=1) \
            or cls.env['account.analytic.plan'].sudo().create({'name': 'خطة اختبار'})
        Analytic = cls.env['account.analytic.account'].sudo()
        Project = cls.env['project.project'].sudo()
        cls.platform_a = Project.create({
            'name': 'منصة اختبار أ',
            'account_id': Analytic.create({'name': 'تحليلي أ', 'plan_id': plan.id}).id,
        })
        cls.platform_b = Project.create({
            'name': 'منصة اختبار ب',
            'account_id': Analytic.create({'name': 'تحليلي ب', 'plan_id': plan.id}).id,
        })

        cls.partner = cls.env['res.partner'].create({'name': 'مندوب الدفعة المقدمة'})
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'مندوب الدفعة المقدمة', 'work_contact_id': cls.partner.id,
        })
        cls.employee._open_platform_history(cls.platform_a, date_start=date(2020, 1, 1))

        cls.gov_entity = cls.env['bank.settlement.government.entity'].sudo().search([], limit=1) \
            or cls.env['bank.settlement.government.entity'].sudo().create({'name': 'جهة اختبار'})
        cls.fee_type = cls.env['bank.settlement.government.fee.type'].sudo().search([], limit=1) \
            or cls.env['bank.settlement.government.fee.type'].sudo().create({'name': 'نوع اختبار'})

        manager_group = cls.env.ref('bank_settlement.group_bank_settlement_manager')
        reviewer_group = cls.env.ref('bank_settlement.group_bank_settlement_reviewer')
        cls.approver = cls.env['res.users'].sudo().create({
            'name': 'معتمِد الدفعة المقدمة', 'login': 'test_prepaid_approver',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                manager_group.id, reviewer_group.id,
            ])],
        })

    def _create_prepaid_fee(self, start_date, days=90, amount=9000.0):
        return self.env['bank.settlement.government.fee'].with_user(self.approver).create({
            'government_entity_id': self.gov_entity.id,
            'fee_type_id': self.fee_type.id,
            'employee_id': self.employee.id,
            'employee_category': 'full_time_rep',
            'amount': amount,
            'is_prepaid': True,
            'prepaid_days': days,
            'prepaid_category_id': self.category.id,
            'journal_id': self.journal.id,
            'transfer_date': start_date,
        })

    def _complete(self, record):
        record.with_user(self.approver).action_submit_review()
        record.with_user(self.approver).action_confirm()
        record.with_user(self.approver).action_done()
        return record

    def _lines(self, record):
        return self.env['bank.settlement.prepaid.line'].sudo().search([
            ('res_model', '=', record._name), ('res_id', '=', record.id),
        ], order='period_start_date')

    # ------------------------------------------------------------------
    def test_schedule_split_is_exact_by_days(self):
        """90 يوماً تبدأ منتصف الشهر: كل فترة بنسبة أيامها الفعلية،
        والمجموع مطابق تماماً للمبلغ الإجمالي."""
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        lines = self._lines(record)
        self.assertTrue(lines)
        self.assertAlmostEqual(sum(lines.mapped('amount')), 9000.0, places=2)
        first = lines[0]
        self.assertEqual(first.period_start_date, date(2026, 3, 16))
        self.assertEqual(first.period_end_date, date(2026, 3, 31))
        # 16 يوماً من أصل 90
        self.assertAlmostEqual(first.amount, round(9000.0 * 16 / 90, 2), places=2)
        self.assertEqual(lines[-1].period_end_date, date(2026, 3, 16) + timedelta(days=89))

    def test_initial_move_is_posted_to_prepaid_account(self):
        """القيد الأولي يُرحَّل فوراً وينعكس في رصيد حساب المصروفات
        المدفوعة مقدماً (كان يبقى مسودة - ثغرة سابقة)."""
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        self.assertTrue(record.move_id)
        self.assertEqual(record.move_id.state, 'posted')
        debit_line = record.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit_line.account_id, self.prepaid_account)
        self.assertAlmostEqual(debit_line.debit, 9000.0, places=2)

    def test_cron_does_not_post_before_period_ends(self):
        """لا تُرحَّل فترة إلا بعد انتهائها فعلياً (ثغرة سابقة: كانت
        تُرحَّل بمجرد بداية الفترة بقيد بتاريخ مستقبلي)."""
        today = date.today()
        record = self._complete(self._create_prepaid_fee(today - timedelta(days=20)))
        self.env['bank.settlement.prepaid.line'].sudo()._cron_generate_due_entries()
        for line in self._lines(record):
            if line.period_end_date <= today:
                self.assertEqual(line.state, 'posted')
                self.assertLessEqual(line.move_id.date, today)
            else:
                self.assertEqual(line.state, 'draft')
                self.assertFalse(line.move_id)

    def test_posted_entry_uses_period_platform_on_both_lines(self):
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        line = self._lines(record)[0]
        line._post_entry()
        expected = str(self.platform_a.account_id.id)
        for move_line in line.move_id.line_ids:
            self.assertEqual((move_line.analytic_distribution or {}).get(expected), 100.0)

    def test_platform_transfer_settles_elapsed_part_with_old_platform(self):
        """نقل المنصة منتصف فترة غير مرحَّلة: الجزء المنقضي يُرحَّل فوراً
        بتوزيع المنصة القديمة، والباقي يتبع الجديدة عند استحقاقه."""
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        second = self._lines(record)[1]
        transfer_date = second.period_start_date + timedelta(days=5)
        self.employee.sudo()._open_platform_history(self.platform_b, date_start=transfer_date)

        settled = self._lines(record).filtered(lambda l: 'تسوية نقل منصة' in (l.name or ''))
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled.state, 'posted')
        old_account = str(self.platform_a.account_id.id)
        for move_line in settled.move_id.line_ids:
            self.assertEqual((move_line.analytic_distribution or {}).get(old_account), 100.0)

        remaining = self.env['bank.settlement.prepaid.line'].browse(second.id)
        self.assertEqual(remaining.state, 'draft')
        self.assertEqual(remaining.period_start_date, transfer_date)
        self.assertAlmostEqual(settled.amount + remaining.amount, 3000.0, places=2)
        remaining._post_entry()
        new_account = str(self.platform_b.account_id.id)
        for move_line in remaining.move_id.line_ids:
            self.assertEqual((move_line.analytic_distribution or {}).get(new_account), 100.0)

    # -- الثغرات المُصلحة ------------------------------------------------
    def test_prepaid_settings_locked_after_execution(self):
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        for vals in ({'prepaid_days': 30}, {'is_prepaid': False},
                     {'prepaid_category_id': self.category.id}):
            with self.assertRaises(UserError):
                record.write(vals)

    def test_cancel_remaining_schedule_stops_future_postings(self):
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        lines = self._lines(record)
        lines[0]._post_entry()
        record.with_user(self.approver).action_cancel_prepaid_schedule()

        lines = self._lines(record)
        self.assertEqual(lines[0].state, 'posted')
        self.assertTrue(all(l.state == 'cancel' for l in lines[1:]))
        # المهمة المجدولة لم تعد تلمسها
        self.env['bank.settlement.prepaid.line'].sudo()._cron_generate_due_entries()
        self.assertTrue(all(l.state == 'cancel' for l in self._lines(record)[1:]))

    def test_cancelled_line_can_be_reactivated_but_posted_cannot_be_cancelled(self):
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        lines = self._lines(record)
        lines[1].action_cancel_line()
        self.assertEqual(lines[1].state, 'cancel')
        lines[1].action_reset_to_draft()
        self.assertEqual(lines[1].state, 'draft')
        lines[0]._post_entry()
        with self.assertRaises(UserError):
            lines[0].action_cancel_line()

    def test_foreign_currency_is_rejected(self):
        """المبالغ تُسجَّل بحقلي مدين/دائن (عملة الشركة دائماً) - فعملة
        مختلفة كانت ستُسجَّل بقيمتها الرقمية خطأً بلا أي تنبيه."""
        other_currency = self.env['res.currency'].sudo().search(
            [('id', '!=', self.company.currency_id.id)], limit=1)
        if not other_currency:
            self.skipTest('لا توجد عملة أخرى في قاعدة الاختبار')
        record = self._create_prepaid_fee(date(2026, 3, 16))
        record.sudo().currency_id = other_currency.id
        record.with_user(self.approver).action_submit_review()
        record.with_user(self.approver).action_confirm()
        with self.assertRaises(UserError):
            record.with_user(self.approver).action_done()

    def test_zero_amount_line_is_cancelled_not_posted(self):
        record = self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        line = self._lines(record)[0]
        line.sudo().write({'amount': 0.0})
        line._post_entry()
        self.assertEqual(line.state, 'cancel')
        self.assertFalse(line.move_id)

    def test_employee_with_prepaid_lines_cannot_be_deleted(self):
        self._complete(self._create_prepaid_fee(date(2026, 3, 16)))
        with self.assertRaises(UserError):
            self.employee.sudo().unlink()
