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
            # company_ids تشمل الفرع الهدف أيضاً - وإلا AccessError عند قراءة
            # اسمه (company.display_name ضمن رسالة الدردشة) بسبب عزل الشركات
            # القياسي بـ Odoo (لا علاقة بصلاحيات قسم الأسطول نفسها).
            'company_ids': [(6, 0, [cls.env.company.id, cls.branch.id])],
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

    def test_transfer_updates_company_even_when_user_lacks_branch_membership(self):
        """ثغرة حقيقية اكتُشفت من الاستخدام الفعلي: نقل سيارة (فردي أو
        جماعي) إلى فرع لا تشمله عضوية المستخدم (قسم الأسطول) في
        company_ids كان يُنشئ سجل تاريخ الفروع بنجاح، لكنه يفشل بصمت في
        تحديث company_id على السيارة نفسها فعلياً - بسبب قاعدة أودو
        الأساسية "Fleet vehicle: Multi Company" (ir_rule_fleet_vehicle)
        التي تقيّد الكتابة على fleet.vehicle بالشركات التي يملك المستخدم
        عضوية فيها. السيارة تبقى ظاهرة بشركتها القديمة حتى بعد تحديث
        الصفحة، بينما "تاريخ الفروع" يُظهر الفترة الجديدة الصحيحة - تناقض
        مباشر لاحظه المستخدم."""
        restricted_user = self.env['res.users'].create({
            'name': 'مسؤول أسطول - بلا عضوية بالفرع الهدف',
            'login': 'fleet_no_branch_membership_user',
            'email': 'fleet_no_branch_membership_user@example.com',
            # عمداً بلا self.branch هنا - فقط الشركة الحالية للسيارة.
            'company_ids': [(6, 0, [self.env.company.id])],
            'company_id': self.env.company.id,
            'group_ids': [(6, 0, [self.fleet_group.id, self.env.ref('base.group_user').id])],
        })

        self.vehicle.with_user(restricted_user)._open_branch_history(
            self.branch, note='نقل تجريبي - بلا عضوية بالفرع',
        )

        self.assertEqual(self.vehicle.company_id, self.branch)
        current = self.vehicle.branch_history_ids.filtered('is_current')
        self.assertEqual(current.company_id, self.branch)

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
        # company_id إجباري (required=True) على مستوى النموذج نفسه - فالمنع
        # يحدث فعلياً عند create() (NotNullViolation) قبل الوصول حتى
        # لـ action_confirm_transfer نفسها؛ نتحقق بـ Exception عامة بدل
        # UserError تحديداً لتغطية الحالتين.
        with self.assertRaises(Exception):
            self.env['fleet.vehicle.branch.transfer.wizard'].create({
                'vehicle_id': self.vehicle.id,
            })

    def test_bulk_wizard_transfers_multiple_vehicles(self):
        """طلب صريح: نقل عدة سيارات دفعة واحدة لفرع مشترك - أغلب سيارات
        الأسطول مسجَّلة على الشركة الأم، ولا يُعقل نقلها للفروع واحدة تلو
        الأخرى."""
        model = self.vehicle.model_id
        other_vehicle = self.env['fleet.vehicle'].create({'model_id': model.id})
        third_vehicle = self.env['fleet.vehicle'].create({'model_id': model.id})

        wizard = self.env['fleet.vehicle.branch.bulk.transfer.wizard'].with_user(
            self.fleet_user
        ).with_context(
            active_ids=(self.vehicle | other_vehicle | third_vehicle).ids,
        ).create({'company_id': self.branch.id})

        self.assertEqual(wizard.vehicle_count, 3)
        wizard.action_confirm_transfer()

        for vehicle in (self.vehicle, other_vehicle, third_vehicle):
            self.assertEqual(vehicle.company_id, self.branch)
            self.assertEqual(vehicle.branch_history_count, 1)

    def test_bulk_wizard_default_get_populates_from_active_ids(self):
        """الفتح من قائمة السيارات (تحديد عدة سيارات ثم "الإجراءات") يملأ
        vehicle_ids تلقائياً من active_ids - بدل اضطرار المستخدم لاختيارها
        يدوياً مرة أخرى."""
        other_vehicle = self.env['fleet.vehicle'].create({'model_id': self.vehicle.model_id.id})

        wizard = self.env['fleet.vehicle.branch.bulk.transfer.wizard'].with_context(
            active_ids=(self.vehicle | other_vehicle).ids,
        ).new({})

        # .new() يُرجع سجلات افتراضية بمعرّفات وهمية (NewId) مرتبطة بمعرّف
        # السجل الحقيقي عبر origin - فلا تُطابق مباشرة (==) السجلات
        # الحقيقية رغم تمثيلها لنفس البيانات؛ نقارن المعرّفات الحقيقية.
        self.assertEqual(
            set(wizard.vehicle_ids.mapped(lambda v: v._origin.id)),
            set((self.vehicle | other_vehicle).ids),
        )

    def test_bulk_wizard_idempotent_for_already_transferred_vehicle(self):
        """سيارة مُنقولة مسبقاً لنفس الفرع الهدف ضمن تحديد جماعي لا يجب أن
        تُسبِّب خطأً أو فترة تاريخية مكررة - بعكس المعالج الفردي الذي يرفض
        هذه الحالة صراحة (هنا الاختلاط متوقَّع ومقبول)."""
        self.vehicle._open_branch_history(self.branch)
        other_vehicle = self.env['fleet.vehicle'].create({'model_id': self.vehicle.model_id.id})

        wizard = self.env['fleet.vehicle.branch.bulk.transfer.wizard'].create({
            'vehicle_ids': [(6, 0, (self.vehicle | other_vehicle).ids)],
            'company_id': self.branch.id,
        })
        wizard.action_confirm_transfer()

        self.assertEqual(self.vehicle.branch_history_count, 1)
        self.assertEqual(other_vehicle.company_id, self.branch)

    def test_bulk_wizard_requires_vehicles(self):
        empty_wizard = self.env['fleet.vehicle.branch.bulk.transfer.wizard'].create({
            'company_id': self.branch.id,
        })
        with self.assertRaises(UserError):
            empty_wizard.action_confirm_transfer()

    def test_bulk_wizard_requires_target_branch(self):
        # company_id إجباري (required=True) على مستوى النموذج نفسه - نفس
        # منطق test_wizard_rejects_without_target_branch للمعالج الفردي.
        with self.assertRaises(Exception):
            self.env['fleet.vehicle.branch.bulk.transfer.wizard'].create({
                'vehicle_ids': [(6, 0, self.vehicle.ids)],
            })

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
