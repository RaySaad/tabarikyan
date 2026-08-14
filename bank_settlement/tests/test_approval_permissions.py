# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestApprovalPermissions(TransactionCase):
    """يتحقق أن "إعادة لمسودة" و"إلغاء" مقيَّدتان بصلاحية مناسبة - لا
    يكفي أن يكون المستخدم "مستخدم" أساسي فقط (أدنى مستوى) لإلغاء اعتماد
    المدير العام أو إلغاء سجل بعد مراجعته."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('bank_settlement.group_bank_settlement_user')
        cls.group_reviewer = cls.env.ref('bank_settlement.group_bank_settlement_reviewer')
        cls.group_manager = cls.env.ref('bank_settlement.group_bank_settlement_manager')
        cls.plain_user = cls.env['res.users'].create({
            'name': 'مستخدم أساسي - سداد بنكي',
            'login': 'bank_settlement_plain_user',
            'email': 'bs_plain_user@example.com',
            'group_ids': [(6, 0, [cls.group_user.id, cls.env.ref('base.group_user').id])],
        })
        cls.reviewer_user = cls.env['res.users'].create({
            'name': 'مراجع - سداد بنكي',
            'login': 'bank_settlement_reviewer_user',
            'email': 'bs_reviewer_user@example.com',
            'group_ids': [(6, 0, [cls.group_reviewer.id, cls.env.ref('base.group_user').id])],
        })
        cls.manager_user = cls.env['res.users'].create({
            'name': 'مدير عام - سداد بنكي',
            'login': 'bank_settlement_manager_user',
            'email': 'bs_manager_user@example.com',
            'group_ids': [(6, 0, [cls.group_manager.id, cls.env.ref('base.group_user').id])],
        })

    def _create_gov_fee(self):
        return self.env['bank.settlement.government.fee'].create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': 500.0,
        })

    def test_settlement_move_created_without_native_accounting_group(self):
        """لا يجوز أن يحتاج مستخدم/مراجع السداد البنكي عضوية حقيقية في
        مجموعة محاسبية أصلية بـ Odoo (فوترة/محاسب) لإكمال السداد - هذا
        كان يفتح لهم رؤية بقية تطبيق المحاسبة رغم أنهم لا يحتاجونها.
        reviewer_user هنا عضو فقط في مجموعات السداد البنكي + المستخدم
        الأساسي، بلا أي مجموعة محاسبية أصلية إطلاقاً."""
        gov_fee = self._create_gov_fee().with_user(self.manager_user)
        gov_fee.action_submit_review()
        gov_fee.action_confirm()
        # دفتر اليومية/الحساب المرتبط لا يُسمح بتحديدهما إلا بعد الاعتماد
        # تحديداً (حالة "مؤكدة").
        gov_fee.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', gov_fee.company_id.id)], limit=1).id,
        })

        gov_fee.with_user(self.reviewer_user).action_done()

        self.assertEqual(gov_fee.state, 'done')
        self.assertTrue(gov_fee.move_id)
        # المراجع يقدر يفتح القيد ويقرأه (زر "عرض القيد") رغم عدم عضويته
        # في أي مجموعة محاسبية أصلية.
        gov_fee.with_user(self.reviewer_user).move_id.read(['name', 'state'])

    def test_user_cannot_read_unrelated_account_move(self):
        """"مستخدم" السداد البنكي يقدر يقرأ فقط القيود التي أنشأها
        السداد البنكي نفسه (is_bank_settlement_move) - أي قيد محاسبي آخر
        في الشركة (فاتورة عميل عادية مثلاً) يجب أن يبقى مخفياً عنه تماماً
        رغم صلاحية القراءة الممنوحة له على نموذج account.move نفسه."""
        unrelated_move = self.env['account.move'].create({'ref': 'قيد غير مرتبط بالسداد البنكي'})
        self.assertFalse(unrelated_move.is_bank_settlement_move)

        found = self.env['account.move'].with_user(self.plain_user).search(
            [('id', '=', unrelated_move.id)]
        )
        self.assertFalse(found, 'يجب ألا يرى مستخدم السداد البنكي قيوداً غير مرتبطة به')

    def test_reset_draft_requires_manager(self):
        gov_fee = self._create_gov_fee().with_user(self.manager_user)
        gov_fee.action_submit_review()
        gov_fee.action_confirm()

        with self.assertRaises(UserError):
            gov_fee.with_user(self.plain_user).action_reset_draft()
        with self.assertRaises(UserError):
            gov_fee.with_user(self.reviewer_user).action_reset_draft()

        gov_fee.with_user(self.manager_user).action_reset_draft()
        self.assertEqual(gov_fee.state, 'draft')

    def test_cancel_requires_reviewer(self):
        gov_fee = self._create_gov_fee()

        with self.assertRaises(UserError):
            gov_fee.with_user(self.plain_user).action_cancel()

        gov_fee.with_user(self.reviewer_user).action_cancel()
        self.assertEqual(gov_fee.state, 'cancel')

    def test_advance_reset_draft_requires_manager(self):
        """السلفة (advance.py) تتجاوز هذه الدوال بنسخة خاصة بها - نفس
        القيد يجب أن يُطبَّق هناك أيضاً."""
        advance = self.env['bank.settlement.advance'].create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id, 'amount': 300.0,
        }).with_user(self.manager_user)
        advance.action_submit_review()
        # لا موظف محدَّد على هذه السلفة، فتُطبَّق آلية الاحتياط (صلاحية
        # المدير العام) بدل اشتراط مسؤول مشروع محدَّد.
        advance.action_pm_approve()
        advance.action_confirm()

        with self.assertRaises(UserError):
            advance.with_user(self.plain_user).action_reset_draft()

        advance.with_user(self.manager_user).action_reset_draft()
        self.assertEqual(advance.state, 'draft')

    def test_advance_cancel_requires_reviewer(self):
        advance = self.env['bank.settlement.advance'].create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id, 'amount': 300.0,
        })

        with self.assertRaises(UserError):
            advance.with_user(self.plain_user).action_cancel()

        advance.with_user(self.reviewer_user).action_cancel()
        self.assertEqual(advance.state, 'cancel')

    def test_advance_confirm_requires_pm_approval_first(self):
        """اعتماد المدير العام لا يجوز إلا بعد موافقة مسؤول المشروع -
        وليس مباشرة بعد الإرسال للمراجعة."""
        advance = self.env['bank.settlement.advance'].create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id, 'amount': 300.0,
        }).with_user(self.manager_user)
        advance.action_submit_review()

        with self.assertRaises(UserError):
            advance.action_confirm()

    def test_advance_pm_approve_requires_specific_project_manager(self):
        """موافقة مسؤول المشروع تتطلب مسؤول مشروع الموظف نفسه تحديداً -
        وليس أي عضو آخر في مجموعة مسؤولي المشاريع."""
        pm_group = self.env.ref('recruitment_workflow.group_recruitment_workflow_project_manager')
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع معيّن - سلفة',
            'login': 'advance_assigned_pm',
            'email': 'advance_assigned_pm@example.com',
            'group_ids': [(6, 0, [pm_group.id, self.env.ref('base.group_user').id])],
        })
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع آخر - سلفة',
            'login': 'advance_other_pm',
            'email': 'advance_other_pm@example.com',
            'group_ids': [(6, 0, [pm_group.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({
            'name': 'مشروع تجريبي - سلفة', 'user_id': assigned_pm.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'موظف سلفة تجريبي', 'project_id': project.id,
        })
        advance = self.env['bank.settlement.advance'].create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0, 'employee_id': employee.id,
        })
        advance.action_submit_review()

        with self.assertRaises(UserError):
            advance.with_user(other_pm).action_pm_approve()

        advance.with_user(assigned_pm).action_pm_approve()
        self.assertEqual(advance.state, 'pm_approved')
