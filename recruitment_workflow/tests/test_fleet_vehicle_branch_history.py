# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFleetVehicleBranchHistory(TransactionCase):
    """يتحقق من زر "نقل لفرع آخر" (تنفيذ فوري + سجل تاريخي دائم) - طلب
    صريح: زر مباشر بلا خط سير موافقة، بعكس نقل المنصة للمناديب."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'ماركة تجريبية - فروع'})
        model = cls.env['fleet.vehicle.model'].create({
            'name': 'موديل تجريبي - فروع', 'brand_id': brand.id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({'model_id': model.id})
        cls.branch = cls.env['res.company'].create({
            'name': 'فرع تجريبي - سيارات', 'parent_id': cls.env.company.id,
        })
        cls.fleet_group = cls.env.ref('recruitment_workflow.group_recruitment_workflow_fleet')
        cls.fleet_user = cls.env['res.users'].create({
            'name': 'مسؤول أسطول - اختبار نقل فرع',
            'login': 'fleet_branch_transfer_user',
            'email': 'fleet_branch_transfer_user@example.com',
            'group_ids': [(6, 0, [cls.fleet_group.id, cls.env.ref('base.group_user').id])],
        })

    def test_transfer_updates_company_and_opens_history_period(self):
        self.assertNotEqual(self.vehicle.company_id, self.branch)

        self.vehicle._open_branch_history(self.branch, note='نقل تجريبي')

        self.assertEqual(self.vehicle.company_id, self.branch)
        self.assertEqual(self.vehicle.branch_history_count, 1)
        current = self.vehicle.branch_history_ids.filtered('is_current')
        self.assertEqual(current.company_id, self.branch)
        self.assertFalse(current.date_end)

    def test_second_transfer_closes_previous_period(self):
        other_branch = self.env['res.company'].create({
            'name': 'فرع تجريبي 2 - سيارات', 'parent_id': self.env.company.id,
        })
        self.vehicle._open_branch_history(self.branch)
        first_period = self.vehicle.branch_history_ids.filtered('is_current')

        self.vehicle._open_branch_history(other_branch)

        self.assertFalse(first_period.is_current)
        self.assertTrue(first_period.date_end)
        self.assertEqual(self.vehicle.company_id, other_branch)
        self.assertEqual(len(self.vehicle.branch_history_ids), 2)

    def test_transfer_to_same_current_branch_does_not_duplicate_period(self):
        self.vehicle._open_branch_history(self.branch)
        count_before = len(self.vehicle.branch_history_ids)

        self.vehicle._open_branch_history(self.branch)

        self.assertEqual(len(self.vehicle.branch_history_ids), count_before)

    def test_branch_history_cannot_be_deleted(self):
        self.vehicle._open_branch_history(self.branch)
        history = self.vehicle.branch_history_ids

        with self.assertRaises(UserError):
            history.unlink()
        self.assertTrue(history.exists())

    def test_wizard_delegates_to_action_and_requires_fleet_group(self):
        wizard = self.env['fleet.vehicle.branch.transfer.wizard'].with_user(self.fleet_user).create({
            'vehicle_id': self.vehicle.id, 'company_id': self.branch.id,
        })

        wizard.action_confirm_transfer()

        self.assertEqual(self.vehicle.company_id, self.branch)

    def test_wizard_rejects_same_branch(self):
        self.vehicle._open_branch_history(self.branch)
        wizard = self.env['fleet.vehicle.branch.transfer.wizard'].create({
            'vehicle_id': self.vehicle.id, 'company_id': self.branch.id,
        })

        with self.assertRaises(UserError):
            wizard.action_confirm_transfer()

    def test_wizard_rejects_without_target_branch(self):
        wizard = self.env['fleet.vehicle.branch.transfer.wizard'].create({
            'vehicle_id': self.vehicle.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_transfer()

    def test_non_fleet_user_cannot_open_transfer_wizard_action(self):
        """مستخدم عادي (بلا مجموعة قسم الأسطول) لا يملك حق إنشاء سجل
        المعالج نفسه - نفس مستوى الصلاحية المطلوب لتنفيذ النقل فعلياً."""
        plain_group = self.env.ref('recruitment_workflow.group_recruitment_workflow_user')
        plain_user = self.env['res.users'].create({
            'name': 'مستخدم عادي - اختبار نقل فرع',
            'login': 'plain_branch_transfer_user',
            'email': 'plain_branch_transfer_user@example.com',
            'group_ids': [(6, 0, [plain_group.id, self.env.ref('base.group_user').id])],
        })

        with self.assertRaises(Exception):
            self.env['fleet.vehicle.branch.transfer.wizard'].with_user(plain_user).create({
                'vehicle_id': self.vehicle.id, 'company_id': self.branch.id,
            })
