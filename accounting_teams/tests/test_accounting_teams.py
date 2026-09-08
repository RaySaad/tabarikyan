# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountingTeams(TransactionCase):
    """يتحقق فعلياً من أن التقييد "يعضّ": محاسب عادي (غير مدير) لا يرى
    دفاتر الفرق الأخرى ولا قيودها ولا بنودها، بينما مدير المحاسبة يرى كل
    شيء - ولا تتأثر أي عملية تعمل بصلاحيات النظام (sudo)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Team = cls.env['account.team']
        cls.team_ar = Team.create({'name': 'فريق الذمم المدينة', 'company_id': cls.company.id})
        cls.team_ap = Team.create({'name': 'فريق الذمم الدائنة', 'company_id': cls.company.id})

        Journal = cls.env['account.journal']
        cls.journal_sale = Journal.create({
            'name': 'مبيعات - اختبار', 'code': 'TSAL', 'type': 'sale',
            'company_id': cls.company.id, 'team_ids': [(6, 0, cls.team_ar.ids)],
        })
        cls.journal_purchase = Journal.create({
            'name': 'مشتريات - اختبار', 'code': 'TPUR', 'type': 'purchase',
            'company_id': cls.company.id, 'team_ids': [(6, 0, cls.team_ap.ids)],
        })
        cls.journal_open = Journal.create({
            'name': 'عمليات متنوعة - اختبار', 'code': 'TMIS', 'type': 'general',
            'company_id': cls.company.id,
        })

        group_invoice = cls.env.ref('account.group_account_invoice')
        group_manager = cls.env.ref('account.group_account_manager')
        group_user = cls.env.ref('account.group_account_user')
        base_user = cls.env.ref('base.group_user')

        def _user(login, name, groups, teams):
            user = cls.env['res.users'].create({
                'name': name, 'login': login,
                'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
                'group_ids': [(6, 0, groups)],
            })
            if teams:
                teams.write({'member_ids': [(4, user.id)]})
            return user

        cls.accountant_ar = _user('test_team_ar', 'محاسب ذمم مدينة',
                                  [base_user.id, group_invoice.id], cls.team_ar)
        cls.accountant_ap = _user('test_team_ap', 'محاسب ذمم دائنة',
                                  [base_user.id, group_invoice.id], cls.team_ap)
        cls.accountant_none = _user('test_team_none', 'محاسب بلا فريق',
                                    [base_user.id, group_invoice.id], None)
        cls.manager = _user('test_team_manager', 'مدير المحاسبة',
                            [base_user.id, group_invoice.id, group_manager.id], None)
        # مستوى "محاسب": كل مزايا المحاسبة (بما فيها شاشة القيود
        # وترحيلها) بلا صلاحية "مدير" - وهو المقصود من هذا المستوى:
        # يعتمد القيود لكنه يبقى محصوراً بدفاتر فريقه.
        cls.accountant_full = _user('test_team_full', 'محاسب كامل - فريق مدينة',
                                    [base_user.id, group_user.id], cls.team_ar)

        cls.move_sale = cls._create_move(cls, cls.journal_sale)
        cls.move_purchase = cls._create_move(cls, cls.journal_purchase)
        cls.move_open = cls._create_move(cls, cls.journal_open)

    def _create_move(self, journal):
        return self.env['account.move'].create({
            'journal_id': journal.id,
            'move_type': 'entry',
            'company_id': journal.company_id.id,
        })

    # ------------------------------------------------------------------
    def _journals_visible_to(self, user):
        return self.env['account.journal'].with_user(user).search([
            ('id', 'in', (self.journal_sale + self.journal_purchase + self.journal_open).ids)
        ])

    def _moves_visible_to(self, user):
        return self.env['account.move'].with_user(user).search([
            ('id', 'in', (self.move_sale + self.move_purchase + self.move_open).ids)
        ])

    def test_accountant_sees_only_own_team_journals_plus_unassigned(self):
        visible = self._journals_visible_to(self.accountant_ar)
        self.assertIn(self.journal_sale, visible)
        self.assertIn(self.journal_open, visible, 'الدفتر بلا فريق يبقى مرئياً للجميع')
        self.assertNotIn(self.journal_purchase, visible)

    def test_other_team_accountant_sees_the_mirror_image(self):
        visible = self._journals_visible_to(self.accountant_ap)
        self.assertIn(self.journal_purchase, visible)
        self.assertIn(self.journal_open, visible)
        self.assertNotIn(self.journal_sale, visible)

    def test_accountant_without_team_sees_only_unassigned_journals(self):
        visible = self._journals_visible_to(self.accountant_none)
        self.assertEqual(visible, self.journal_open)

    def test_manager_sees_everything(self):
        journals = self._journals_visible_to(self.manager)
        self.assertIn(self.journal_sale, journals)
        self.assertIn(self.journal_purchase, journals)
        self.assertIn(self.journal_open, journals)
        moves = self._moves_visible_to(self.manager)
        self.assertEqual(len(moves), 3)

    def test_moves_follow_journal_access(self):
        visible = self._moves_visible_to(self.accountant_ar)
        self.assertIn(self.move_sale, visible)
        self.assertIn(self.move_open, visible)
        self.assertNotIn(self.move_purchase, visible)

    def test_move_lines_follow_journal_access(self):
        line = self.env['account.move.line'].with_user(self.accountant_ar).search([
            ('journal_id', '=', self.journal_purchase.id),
        ])
        self.assertFalse(line, 'بنود دفتر فريق آخر يجب ألا تظهر')

    def test_reading_forbidden_move_raises(self):
        with self.assertRaises(AccessError):
            self.move_purchase.with_user(self.accountant_ar).read(['name'])

    def test_sudo_automation_is_not_affected(self):
        """كل الأتمتة الداخلية (السداد البنكي، الدفعات المقدمة، رسوم
        التوظيف) تعمل بصلاحيات النظام - يجب ألا تتأثر بأي تقييد فرق."""
        moves = self.env['account.move'].with_user(self.accountant_ar).sudo().search([
            ('id', 'in', (self.move_sale + self.move_purchase + self.move_open).ids)
        ])
        self.assertEqual(len(moves), 3)

    def test_member_from_another_company_is_rejected(self):
        other_company = self.env['res.company'].create({'name': 'شركة أخرى - اختبار'})
        outsider = self.env['res.users'].create({
            'name': 'مستخدم شركة أخرى', 'login': 'test_team_outsider',
            'company_id': other_company.id, 'company_ids': [(6, 0, other_company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(ValidationError):
            self.team_ar.write({'member_ids': [(4, outsider.id)]})

    def test_duplicate_team_name_in_same_company_rejected(self):
        with self.assertRaises(Exception):
            self.env['account.team'].create({
                'name': 'فريق الذمم المدينة', 'company_id': self.company.id,
            })

    def test_journal_and_team_are_two_sides_of_one_relation(self):
        self.assertIn(self.journal_sale, self.team_ar.journal_ids)
        self.assertNotIn(self.journal_purchase, self.team_ar.journal_ids)

    # ------------------------------------------------------------------
    # قواعد المبيعات/المشتريات كانت تمنح الرؤية حسب *نوع* الفاتورة بغض
    # النظر عن الدفتر - وهي السبب الفعلي في بقاء مستخدم يرى فواتير خارج
    # فرقه رغم تقييد كل الدفاتر. هذه الاختبارات تثبت إغلاق تلك الثغرة.
    # ------------------------------------------------------------------
    # ================= مستوى "محاسب" (اعتماد بلا صلاحية مدير) =========
    def test_accountant_level_is_selectable_in_user_form(self):
        """بدون privilege_id لا يظهر المستوى في خانة المحاسبة إطلاقاً،
        فيُضطر من يحتاج ترحيل القيود لاختيار "مدير" - وهو معفى من
        الفرق. هذا الاختبار يحرس سبب وجود التعديل كله."""
        group = self.env.ref('account.group_account_user')
        self.assertEqual(group.privilege_id,
                         self.env.ref('account.res_groups_privilege_accounting'))
        self.assertGreater(group.sequence,
                           self.env.ref('account.group_account_invoice').sequence)
        self.assertLess(group.sequence,
                        self.env.ref('account.group_account_manager').sequence)

    def test_accountant_level_reaches_the_journal_entries_menu(self):
        """قائمة "القيود اليومية" تتطلب group_account_readonly - والمستوى
        يشتقّها، وإلا كانت الشاشة محجوبة عنه ولا فائدة من المستوى."""
        self.assertIn(self.env.ref('account.group_account_readonly'),
                      self.accountant_full.all_group_ids)
        menu = self.env.ref('account.menu_finance_entries')
        self.assertTrue(menu.with_user(self.accountant_full)._filter_visible_menus())

    def test_accountant_level_is_still_restricted_to_his_teams(self):
        """جوهر الحل: صلاحية الاعتماد لا تفتح له دفاتر الفرق الأخرى."""
        visible = self._moves_visible_to(self.accountant_full)
        self.assertIn(self.move_sale, visible)
        self.assertIn(self.move_open, visible)
        self.assertNotIn(self.move_purchase, visible)
        self.assertNotIn(self.journal_purchase,
                         self._journals_visible_to(self.accountant_full))

    def test_accountant_level_can_create_and_post_in_his_own_journal(self):
        """وأنه يرحّل فعلاً - لا يكتفي بالرؤية."""
        accounts = self.env['account.account'].search(
            [('company_ids', 'in', self.company.id)], limit=2)
        if len(accounts) < 2:
            self.skipTest('لا يوجد دليل حسابات في قاعدة الاختبار')
        move = self.env['account.move'].with_user(self.accountant_full).create({
            'journal_id': self.journal_open.id,
            'move_type': 'entry',
            'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'account_id': accounts[0].id, 'balance': 100.0}),
                (0, 0, {'account_id': accounts[1].id, 'balance': -100.0}),
            ],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_accountant_level_cannot_post_outside_his_teams(self):
        """والحد الآخر: لا يستطيع لمس قيد دفتر خارج فريقه."""
        with self.assertRaises(AccessError):
            self.move_purchase.with_user(self.accountant_full).action_post()

    def _sales_user(self, login, teams=None):
        groups = [self.env.ref('base.group_user').id,
                  self.env.ref('account.group_account_invoice').id]
        sale_group = self.env.ref('sales_team.group_sale_salesman_all_leads',
                                  raise_if_not_found=False)
        if sale_group:
            groups.append(sale_group.id)
        user = self.env['res.users'].create({
            'name': login, 'login': login,
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, groups)],
        })
        if teams:
            teams.write({'member_ids': [(4, user.id)]})
        return user

    def _customer_invoice(self, journal):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'partner_id': self.env['res.partner'].create({'name': 'عميل اختبار'}).id,
        })

    def test_sales_user_cannot_see_invoices_outside_his_teams(self):
        if not self.env.ref('sales_team.group_sale_salesman_all_leads',
                            raise_if_not_found=False):
            self.skipTest('موديول المبيعات غير مثبَّت')
        invoice = self._customer_invoice(self.journal_sale)
        # مستخدم مبيعات في فريق الذمم الدائنة (لا يملك دفتر المبيعات)
        outsider = self._sales_user('test_sales_outsider', self.team_ap)
        visible = self.env['account.move'].with_user(outsider).search([
            ('id', '=', invoice.id)])
        self.assertFalse(
            visible,
            'قاعدة المبيعات كانت تُظهر كل فواتير العملاء بغض النظر عن الفريق')

    def test_sales_user_sees_invoices_of_his_team(self):
        if not self.env.ref('sales_team.group_sale_salesman_all_leads',
                            raise_if_not_found=False):
            self.skipTest('موديول المبيعات غير مثبَّت')
        invoice = self._customer_invoice(self.journal_sale)
        insider = self._sales_user('test_sales_insider', self.team_ar)
        visible = self.env['account.move'].with_user(insider).search([
            ('id', '=', invoice.id)])
        self.assertEqual(visible, invoice)

    def test_patch_is_idempotent_across_updates(self):
        """تكرار التطبيق يجب ألا يراكم الشرط في المجال."""
        from odoo.addons.accounting_teams import _apply_team_rules
        rule = self.env.ref('account.account_move_see_all')
        _apply_team_rules(self.env)
        first = rule.domain_force
        _apply_team_rules(self.env)
        self.assertEqual(rule.domain_force, first)
        # شرط الفريق يظهر مرتين (طرفا الشرط) ولا يتراكم مع التكرار.
        # ملاحظة: العدّ على 'journal_id.team_ids' تحديداً - لأن
        # 'accounting_team_ids' يحتوي 'team_ids' كسلسلة فرعية أيضاً.
        self.assertEqual(rule.domain_force.count('journal_id.team_ids'), 2)

    # ------------------------------------------------------------------
    # قاعدة السداد البنكي كانت تُظهر كل قيود السداد (رسوم حكومية، سلف،
    # تأمين، استحقاقات دفعات مقدمة) في أي دفتر لمن يملك صلاحية السداد -
    # حتى لو كان فريقه لا يضم ذلك الدفتر إطلاقاً.
    # ------------------------------------------------------------------
    def _settlement_move(self, journal):
        move = self.env['account.move'].create({
            'journal_id': journal.id, 'move_type': 'entry',
            'company_id': journal.company_id.id,
        })
        if 'is_bank_settlement_move' in move._fields:
            move.is_bank_settlement_move = True
        return move

    def test_bank_settlement_moves_follow_journal_teams(self):
        bs_group = self.env.ref('bank_settlement.group_bank_settlement_user',
                                raise_if_not_found=False)
        if not bs_group:
            self.skipTest('موديول السداد البنكي غير مثبَّت')

        settlement_in_ap = self._settlement_move(self.journal_purchase)
        settlement_in_ar = self._settlement_move(self.journal_sale)

        user = self.env['res.users'].create({
            'name': 'موظف سداد بنكي', 'login': 'test_bs_user',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, bs_group.id])],
        })
        self.team_ar.write({'member_ids': [(4, user.id)]})

        visible = self.env['account.move'].with_user(user).search([
            ('id', 'in', (settlement_in_ap + settlement_in_ar).ids)])
        self.assertIn(settlement_in_ar, visible, 'قيد سداد في دفتر فريقه: يجب أن يراه')
        self.assertNotIn(
            settlement_in_ap, visible,
            'قيد سداد في دفتر خارج فريقه: كان يظهر رغم التقييد - هذه هي الثغرة')

    def test_bank_settlement_user_without_team_sees_nothing_outside_open_journals(self):
        bs_group = self.env.ref('bank_settlement.group_bank_settlement_user',
                                raise_if_not_found=False)
        if not bs_group:
            self.skipTest('موديول السداد البنكي غير مثبَّت')
        settlement = self._settlement_move(self.journal_purchase)
        user = self.env['res.users'].create({
            'name': 'موظف سداد بلا فريق', 'login': 'test_bs_no_team',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, bs_group.id])],
        })
        visible = self.env['account.move'].with_user(user).search([('id', '=', settlement.id)])
        self.assertFalse(visible)

    def test_team_membership_change_takes_effect_immediately(self):
        """أودو تُخزّن مجال القاعدة مؤقتاً لكل مستخدم بعد تعويض فرقه فيه -
        فبلا تفريغ تلك الذاكرة كانت إضافة موظف لفريق بلا أي أثر حتى
        إعادة تشغيل الخادم (المدير يضيف العضو ولا يتغيّر شيء)."""
        newcomer = self.env['res.users'].create({
            'name': 'محاسب جديد', 'login': 'test_team_newcomer',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_invoice').id,
            ])],
        })
        # قبل الانضمام: لا يرى قيد دفتر المبيعات
        before = self.env['account.move'].with_user(newcomer).search([
            ('id', '=', self.move_sale.id)])
        self.assertFalse(before)

        # بعد الانضمام مباشرة (بلا إعادة تشغيل): يراه
        self.team_ar.write({'member_ids': [(4, newcomer.id)]})
        after = self.env['account.move'].with_user(newcomer).search([
            ('id', '=', self.move_sale.id)])
        self.assertEqual(after, self.move_sale)

        # وبإخراجه من الفريق يختفي فوراً كذلك
        self.team_ar.write({'member_ids': [(3, newcomer.id)]})
        removed = self.env['account.move'].with_user(newcomer).search([
            ('id', '=', self.move_sale.id)])
        self.assertFalse(removed)
