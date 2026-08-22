# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSettlementAdminDelete(TransactionCase):
    """يتحقق من "الحذف النهائي الإداري" - أداة استثنائية مُغلَقة افتراضياً
    (معامل نظام bank_settlement.admin_delete_enabled)، لتنظيف بيانات
    خاطئة/تجريبية وصلت لأي مرحلة
    - أهم ما يُتحقَّق منه: قيد محاسبي مرحّل (Posted) لا يُحذف نهائياً
    أبداً، بل يُعكَس بقيد مقابل مرحّل أيضاً (نفس الأسلوب المحاسبي
    السليم)، بينما قيد لا يزال مسودة يُحذف مباشرة بلا مشكلة.

    ملاحظة تنفيذية: TransactionCase يُشغِّل الاختبارات افتراضياً باسم
    المستخدم superuser (uid=1، __system__) - وهو ليس عضواً تلقائياً في
    group_bank_settlement_manager (فقط base.user_admin مُضاف صراحة لها
    عبر security.xml). لذا كل عملية تتطلب هذه الصلاحية فعلياً هنا تُنفَّذ
    صراحة عبر with_user(self.manager_user) بدل الاعتماد على المستخدم
    الافتراضي."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.GovFee = cls.env['bank.settlement.government.fee']
        cls.ConfigParam = cls.env['ir.config_parameter'].sudo()
        cls.manager_group = cls.env.ref('bank_settlement.group_bank_settlement_manager')
        cls.reviewer_group = cls.env.ref('bank_settlement.group_bank_settlement_reviewer')
        # base.user_admin هو المستخدم الوحيد المُضاف صراحة لمجموعة مدير
        # عام السداد البنكي في بيانات التنصيب (security.xml) - نستخدمه
        # كـ"مدير" جاهز بدل إنشاء مستخدم جديد وإضافته للمجموعة يدوياً.
        cls.manager_user = cls.env.ref('base.user_admin')

    def _create_gov_fee(self):
        return self.GovFee.create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': 500.0,
        })

    def _complete_to_done(self, rec):
        rec = rec.with_user(self.manager_user)
        rec.action_submit_review()
        rec.action_confirm()
        rec.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', rec.company_id.id)], limit=1).id,
        })
        rec.action_done()
        return rec

    def _enable_admin_delete(self):
        self.ConfigParam.set_param('bank_settlement.admin_delete_enabled', 'True')

    def _disable_admin_delete(self):
        self.ConfigParam.set_param('bank_settlement.admin_delete_enabled', 'False')

    def _reviewer_only_user(self, login):
        return self.env['res.users'].create({
            'name': 'محاسب - اختبار حذف إداري %s' % login,
            'login': login,
            'email': '%s@example.com' % login,
            'group_ids': [(6, 0, [self.reviewer_group.id, self.env.ref('base.group_user').id])],
        })

    # -- التفعيل/الإيقاف ---------------------------------------------------

    def test_admin_delete_blocked_when_disabled_by_default(self):
        """المعامل مُغلَق افتراضياً (False) - لا يُمكِّن أي شخص من الحذف
        النهائي حتى لو كان مديراً عاماً، قبل تفعيله صراحة."""
        gov_fee = self._create_gov_fee()

        with self.assertRaises(UserError):
            gov_fee.with_user(self.manager_user).action_admin_force_delete(reason='محاولة بلا تفعيل')
        with self.assertRaises(UserError):
            gov_fee.with_user(self.manager_user).action_open_admin_delete_wizard()
        self.assertTrue(gov_fee.exists())

    def test_admin_delete_enabled_field_reflects_parameter(self):
        gov_fee = self._create_gov_fee()
        self.assertFalse(gov_fee.admin_delete_enabled)

        self._enable_admin_delete()
        gov_fee.invalidate_recordset(['admin_delete_enabled'])

        self.assertTrue(gov_fee.admin_delete_enabled)
        self._disable_admin_delete()

    # -- الصلاحيات والسبب ----------------------------------------------------

    def test_admin_delete_requires_reason(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()

        with self.assertRaises(UserError):
            gov_fee.with_user(self.manager_user).action_admin_force_delete(reason=False)
        self.assertTrue(gov_fee.exists())
        self._disable_admin_delete()

    def test_admin_delete_requires_manager_group(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        reviewer_user = self._reviewer_only_user('admin_delete_reviewer_only')

        with self.assertRaises(UserError):
            gov_fee.with_user(reviewer_user).action_admin_force_delete(reason='محاولة غير مصرَّح بها')
        self.assertTrue(gov_fee.exists())
        self._disable_admin_delete()

    # -- الحذف الفعلي وتسجيل الأثر --------------------------------------------

    def test_admin_delete_removes_draft_record_and_logs(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        name = gov_fee.name

        gov_fee.with_user(self.manager_user).action_admin_force_delete(reason='سجل تجريبي بالخطأ')

        self.assertFalse(gov_fee.exists())
        log = self.env['bank.settlement.deletion.log'].search([('record_name', '=', name)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.reason, 'سجل تجريبي بالخطأ')
        self.assertEqual(log.deleted_by, self.manager_user)
        self.assertFalse(log.move_name)
        self._disable_admin_delete()

    def test_admin_delete_with_draft_move_deletes_move_directly(self):
        """قيد محاسبي لا يزال مسودة (لم يُرحَّل بعد) - يُحذف مباشرة بلا
        أي عكس، لأنه ليس له أثر محاسبي رسمي بعد."""
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        gov_fee = self._complete_to_done(gov_fee)
        move = gov_fee.move_id
        self.assertEqual(move.state, 'draft')

        gov_fee.with_user(self.manager_user).action_admin_force_delete(reason='قيد مسودة - تنظيف')

        self.assertFalse(gov_fee.exists())
        self.assertFalse(move.exists())
        self._disable_admin_delete()

    def test_admin_delete_with_posted_move_reverses_instead_of_deleting(self):
        """الحالة الأهم: قيد محاسبي مرحّل (Posted) - يجب ألا يُحذف نهائياً
        أبداً، بل يُعكَس بقيد مقابل مرحّل أيضاً يُصفّر أثره المالي، مع
        بقاء القيد الأصلي نفسه موجوداً وسليماً في دفاتر المحاسبة."""
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        gov_fee = self._complete_to_done(gov_fee)
        move = gov_fee.move_id
        move.with_user(self.manager_user).action_post()
        self.assertEqual(move.state, 'posted')
        move_name = move.name

        gov_fee.with_user(self.manager_user).action_admin_force_delete(
            reason='بيانات خاطئة لكن القيد مرحّل',
        )

        self.assertFalse(gov_fee.exists())
        # القيد الأصلي يبقى موجوداً ومرحّلاً - لم يُحذف.
        self.assertTrue(move.exists())
        self.assertEqual(move.state, 'posted')
        # قيد عكسي جديد مرحّل أيضاً يشير إليه.
        reversal = self.env['account.move'].search([('reversed_entry_id', '=', move.id)])
        self.assertEqual(len(reversal), 1)
        self.assertEqual(reversal.state, 'posted')
        log = self.env['bank.settlement.deletion.log'].search(
            [('move_name', '=', move_name)]
        )
        self.assertEqual(len(log), 1)
        self.assertIn('عُكس', log.move_status_at_deletion)
        self._disable_admin_delete()

    def test_deletion_log_cannot_be_unlinked(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        gov_fee.with_user(self.manager_user).action_admin_force_delete(reason='لاختبار منع حذف السجل')
        log = self.env['bank.settlement.deletion.log'].search([], limit=1, order='id desc')

        with self.assertRaises(UserError):
            log.unlink()
        self._disable_admin_delete()

    # -- المعالج (الواجهة) ----------------------------------------------------

    def test_admin_delete_wizard_requires_exact_confirmation_text(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        wizard = self.env['bank.settlement.admin.delete.wizard'].with_user(self.manager_user).create({
            'res_model': gov_fee._name, 'res_id': gov_fee.id,
            'reason': 'سبب', 'confirmation_text': 'نص خاطئ',
        })

        with self.assertRaises(UserError):
            wizard.action_confirm_delete()
        self.assertTrue(gov_fee.exists())
        self._disable_admin_delete()

    def test_admin_delete_wizard_delegates_to_action(self):
        self._enable_admin_delete()
        gov_fee = self._create_gov_fee()
        wizard = self.env['bank.settlement.admin.delete.wizard'].with_user(self.manager_user).create({
            'res_model': gov_fee._name, 'res_id': gov_fee.id,
            'reason': 'سبب صحيح', 'confirmation_text': 'حذف نهائي',
        })

        wizard.action_confirm_delete()

        self.assertFalse(gov_fee.exists())
        self._disable_admin_delete()
