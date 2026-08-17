# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrEmployeeCost(TransactionCase):
    """يتحقق من قيد المبلغ الموجب ومنع الحذف النهائي بعد مغادرة "مسودة"
    - ثغرتان حقيقيتان مكتشفتان بمراجعة شاملة: لم يكن يوجد أي تحقق من
    كون المبلغ موجباً، ولا أي حماية من الحذف النهائي رغم إنشاء فاتورة
    مورد حقيقية (بعكس recruitment_request.py الذي يمنع الحذف تماماً
    لنفس السبب)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Cost = cls.env['hr.employee.cost']
        cls.project = cls.env['project.project'].create({'name': 'منصة تجريبية - تكاليف'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'موظف تجريبي - تكاليف', 'project_id': cls.project.id,
        })
        cls.cost_type = cls.env['hr.employee.cost.type'].create({
            'name': 'تجديد إقامة - اختبار',
            'expense_account_id': cls.env['account.account'].search([], limit=1).id,
        })

    def _create_cost(self, **kwargs):
        vals = {
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'cost_type_id': self.cost_type.id,
            'amount': 500.0,
        }
        vals.update(kwargs)
        return self.Cost.create(vals)

    def test_amount_must_be_positive(self):
        with self.assertRaises(UserError):
            self._create_cost(amount=-100.0)
        with self.assertRaises(UserError):
            self._create_cost(amount=0.0)

    def test_draft_cost_can_be_deleted(self):
        cost = self._create_cost()
        cost.unlink()
        self.assertFalse(cost.exists())

    def test_submitted_cost_cannot_be_deleted(self):
        """بعد رفعها للمحاسبة (فاتورة مورد حقيقية أُنشئت) - لا يجوز حذفها
        نهائياً، للحفاظ على سجل تدقيق كامل يفسّر وجود تلك الفاتورة."""
        partner = self.env['res.partner'].create({'name': 'مورد تجريبي - تكاليف'})
        cost = self._create_cost(partner_id=partner.id)
        cost.action_submit_to_accounting()
        self.assertEqual(cost.state, 'submitted')

        with self.assertRaises(UserError):
            cost.unlink()
        self.assertTrue(cost.exists())

    def test_cancelled_cost_cannot_be_deleted(self):
        cost = self._create_cost()
        cost.action_cancel()
        self.assertEqual(cost.state, 'cancelled')

        with self.assertRaises(UserError):
            cost.unlink()

    def test_submit_to_accounting_notifies_accountant(self):
        """كانت التكلفة تُرفع لفريق المحاسبة بلا أي إشعار فعلي - يجب أن
        يصلهم نشاط (Activity) تلقائي بدل تفقّد فواتير الموردين يدوياً."""
        partner = self.env['res.partner'].create({'name': 'مورد تجريبي - إشعار'})
        cost = self._create_cost(partner_id=partner.id)

        cost.action_submit_to_accounting()

        self.assertTrue(cost.activity_ids)
        notified_user = cost.activity_ids[:1].user_id
        self.assertTrue(
            notified_user.has_group('recruitment_workflow.group_recruitment_workflow_accountant'),
            'المستخدَم المُخطَر يجب أن يكون عضواً في مجموعة المحاسب فعلياً.',
        )
