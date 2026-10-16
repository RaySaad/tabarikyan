# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVehicleOwnershipGuards(TransactionCase):
    """ملكية المركبة لا تُنقل من الفرع.

    السيناريو الذي يحميه هذا الملف: مستخدم في فرع يملك صلاحية تعديل
    المركبات (مشرف الحركة مثلاً) ينقل شركة المركبة إلى فرعه، فتخرج من
    دفاتر الأسطول وتتوقف أجرتها - ثم "يؤجّرها" لفرعه كأنها ملكه."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.fleet_company = Company.create({
            'name': 'أسطول الملكية (اختبار)', 'is_fleet_owner': True})
        cls.branch = Company.create({'name': 'فرع الملكية (اختبار)'})

        model = cls.env['fleet.vehicle.model'].search([], limit=1)
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id, 'license_plate': 'OWN-1',
            'company_id': cls.fleet_company.id, 'rental_monthly_rate': 2000.0,
        })
        cls.contract = cls.env['fleet.rental.contract'].create({
            'company_id': cls.branch.id, 'vehicle_id': cls.vehicle.id,
            'monthly_rate': 2000.0, 'date_start': '2026-01-01',
        })

        # مشرف الحركة: دور فرعي يملك تعديل المركبات عبر مجموعة أودو.
        cls.branch_officer = cls.env['res.users'].create({
            'name': 'مشرف حركة الفرع', 'login': 'branch_fleet_officer',
            'company_id': cls.branch.id,
            'company_ids': [(6, 0, [cls.branch.id])],
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_fleet_supervisor').id),
            ],
        })
        cls.fleet_manager = cls.env['res.users'].create({
            'name': 'مدير الحركة (ملكية)', 'login': 'fleet_owner_manager',
            'company_id': cls.fleet_company.id,
            'company_ids': [(6, 0, [cls.fleet_company.id])],
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'recruitment_workflow.group_recruitment_workflow_fleet_manager').id),
            ],
        })

    # ------------------------------------------------------------------
    def test_branch_cannot_move_rented_vehicle(self):
        """الثغرة الأصلية: نقل الملكية من داخل الفرع.

        الحارس في النموذج يسبق فحص الصلاحيات، فالخطأ منه."""
        with self.assertRaises(UserError):
            self.vehicle.with_user(self.branch_officer).write(
                {'company_id': self.branch.id})
        self.assertEqual(self.vehicle.company_id, self.fleet_company)

    def test_branch_cannot_move_vehicle_even_after_contract_ends(self):
        """الطبقة الثانية: بلا عقد يسكت الحارس، فتردّ قاعدة الصلاحيات."""
        self.contract.with_user(self.fleet_manager).action_end()
        with self.assertRaises(AccessError):
            self.vehicle.with_user(self.branch_officer).write(
                {'company_id': self.branch.id})
        self.assertEqual(self.vehicle.company_id, self.fleet_company)

    def test_branch_cannot_archive_rented_vehicle(self):
        with self.assertRaises(UserError):
            self.vehicle.with_user(self.branch_officer).write({'active': False})
        self.assertTrue(self.vehicle.active)

    def test_fleet_cannot_move_vehicle_while_rented(self):
        """حتى الأسطول: نقل مركبة مؤجَّرة يقطع سلسلة الأجرة."""
        with self.assertRaises(UserError):
            self.vehicle.with_user(self.fleet_manager).write(
                {'company_id': self.branch.id})

    def test_fleet_can_move_vehicle_after_contract_ends(self):
        self.contract.with_user(self.fleet_manager).action_end()
        self.vehicle.with_user(self.fleet_manager).write(
            {'company_id': self.branch.id})
        self.assertEqual(self.vehicle.company_id, self.branch)

    def test_contract_vehicle_must_belong_to_fleet_company(self):
        """"تأجير" مركبة يملكها الفرع نفسه بلا معنى - ويولّد قيداً
        محاسبياً من الشركة إلى نفسها."""
        branch_owned = self.env['fleet.vehicle'].create({
            'model_id': self.vehicle.model_id.id, 'license_plate': 'OWN-2',
            'company_id': self.branch.id, 'rental_monthly_rate': 1000.0,
        })
        with self.assertRaises(ValidationError):
            self.env['fleet.rental.contract'].create({
                'company_id': self.branch.id, 'vehicle_id': branch_owned.id,
                'monthly_rate': 1000.0, 'date_start': '2026-02-01',
            })

    def test_contract_renter_differs_from_owner(self):
        with self.assertRaises(ValidationError):
            self.env['fleet.rental.contract'].create({
                'company_id': self.fleet_company.id,
                'vehicle_id': self.vehicle.id,
                'monthly_rate': 2000.0, 'date_start': '2026-02-01',
            })

    def test_branch_still_reads_its_rented_vehicle(self):
        """الضابط المقابل: الإغلاق لا يُلغي ما بُني أمس."""
        visible = self.env['fleet.vehicle'].with_user(
            self.branch_officer).search([('id', '=', self.vehicle.id)])
        self.assertTrue(visible, 'الفرع فقد رؤية مركبته المؤجَّرة')
