# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHrEmployeePlatformBulkAssign(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env['hr.employee']
        cls.Wizard = cls.env['hr.employee.platform.bulk.assign.wizard']
        cls.project = cls.env['project.project'].create({'name': 'منصة تجريبية للربط الجماعي'})

    def test_bulk_assign_links_employees_without_prior_platform(self):
        """الربط الجماعي يعمل للموظفين القدامى الذين لا منصة لهم أصلاً -
        يُنشئ سجل تاريخ منصات لكل واحد منهم ويحدّث المنصة الحالية."""
        employees = self.Employee.create([
            {'name': 'موظف قديم 1'},
            {'name': 'موظف قديم 2'},
        ])
        self.assertFalse(employees.mapped('project_id').filtered(lambda p: p))

        wizard = self.Wizard.create({
            'project_id': self.project.id,
            'note': 'ربط رجعي - اختبار',
            'line_ids': [
                (0, 0, {'employee_id': employee.id, 'date_start': date.today()})
                for employee in employees
            ],
        })
        wizard.action_confirm_assign()

        for employee in employees:
            self.assertEqual(employee.project_id, self.project)
            self.assertEqual(len(employee.platform_history_ids), 1)
            self.assertTrue(employee.platform_history_ids.is_current)

    def test_bulk_assign_does_not_duplicate_open_period_for_same_project(self):
        """موظف مرتبط أصلاً بنفس المنصة لا يُنشأ له سجل تاريخ مكرر."""
        employee = self.Employee.create({'name': 'موظف مرتبط مسبقاً'})
        employee._open_platform_history(self.project)
        self.assertEqual(len(employee.platform_history_ids), 1)

        wizard = self.Wizard.create({
            'project_id': self.project.id,
            'line_ids': [(0, 0, {'employee_id': employee.id, 'date_start': date.today()})],
        })
        wizard.action_confirm_assign()

        self.assertEqual(len(employee.platform_history_ids), 1)

    def test_bulk_assign_uses_custom_start_date(self):
        """تاريخ البداية يجب أن يعكس التاريخ الذي يحدّده المستخدم (ربط
        رجعي) وليس دائماً تاريخ اليوم."""
        employee = self.Employee.create({'name': 'موظف قديم بتاريخ رجعي'})
        past_date = date.today() - timedelta(days=365)

        wizard = self.Wizard.create({
            'project_id': self.project.id,
            'line_ids': [(0, 0, {'employee_id': employee.id, 'date_start': past_date})],
        })
        wizard.action_confirm_assign()

        self.assertEqual(employee.platform_history_ids.date_start, past_date)

    def test_bulk_assign_default_date_from_employee_create_date(self):
        """عند فتح المعالج من قائمة الموظفين، التاريخ المقترح لكل سطر هو
        تاريخ إنشاء سجل الموظف تلقائياً - وهو ما يعكس تاريخ تعيينه الفعلي
        لهؤلاء الموظفين القدامى - مع بقائه قابلاً للتعديل يدوياً."""
        employee = self.Employee.create({'name': 'موظف بتاريخ إنشاء محدد'})

        wizard = self.Wizard.with_context(active_ids=employee.ids).create({
            'project_id': self.project.id,
        })

        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids.employee_id, employee)
        self.assertEqual(wizard.line_ids.date_start, employee.create_date.date())

    def test_bulk_assign_rejects_line_without_employee(self):
        """سطر بدون موظف محدد (مثال: أُضيف يدوياً في الواجهة بدون تعبئة)
        يجب أن يُرفض برسالة واضحة بدل انهيار قيد NOT NULL في قاعدة
        البيانات."""
        wizard = self.Wizard.create({'project_id': self.project.id})
        wizard.line_ids = [(0, 0, {'date_start': date.today()})]

        with self.assertRaises(UserError):
            wizard.action_confirm_assign()

    # ------------------------------------------------------------------
    # مزامنة نموذج التوزيع التحليلي لشريك المندوب الشخصي مع منصته الحالية
    # ------------------------------------------------------------------
    def test_open_platform_history_syncs_partner_analytic_distribution(self):
        """ربط أول مرة بمنصة يجب أن ينشئ نموذج توزيع تحليلي (account.
        analytic.distribution.model) لشريك المندوب الشخصي، يقترح حساب
        المنصة تلقائياً على أي فاتورة/قيد مستقبلي لهذا الشريك."""
        partner = self.env['res.partner'].create({'name': 'شريك مندوب تجريبي'})
        employee = self.Employee.create({
            'name': 'مندوب له شريك شخصي', 'work_contact_id': partner.id,
        })

        employee._open_platform_history(self.project)

        self.assertTrue(self.project.account_id)
        DistModel = self.env['account.analytic.distribution.model']
        distribution = DistModel.search([('partner_id', '=', partner.id)])
        self.assertEqual(len(distribution), 1)
        self.assertEqual(
            distribution.analytic_distribution,
            {str(self.project.account_id.id): 100.0},
        )

    def test_platform_transfer_updates_existing_partner_analytic_distribution(self):
        """النقل لمنصة أخرى يجب أن يحدّث نفس نموذج التوزيع التحليلي
        (وليس إنشاء نموذج مكرر) ليعكس حساب المنصة الجديدة."""
        partner = self.env['res.partner'].create({'name': 'شريك مندوب منقول'})
        employee = self.Employee.create({
            'name': 'مندوب سينتقل', 'work_contact_id': partner.id,
        })
        other_project = self.env['project.project'].create({'name': 'منصة أخرى للنقل'})

        employee._open_platform_history(self.project)
        employee._open_platform_history(other_project)

        DistModel = self.env['account.analytic.distribution.model']
        distribution = DistModel.search([('partner_id', '=', partner.id)])
        self.assertEqual(len(distribution), 1)
        self.assertEqual(
            distribution.analytic_distribution,
            {str(other_project.account_id.id): 100.0},
        )

    def test_open_platform_history_no_crash_without_personal_partner(self):
        """موظف بدون أي شريك شخصي (لا work_contact_id ولا مستخدم مرتبط)
        لا يجب أن يتسبب في أي خطأ - فقط يتخطى إنشاء نموذج التوزيع."""
        employee = self.Employee.create({'name': 'مندوب بدون شريك'})

        employee._open_platform_history(self.project)

        self.assertEqual(employee.project_id, self.project)


@tagged('post_install', '-at_install')
class TestHrEmployeePlatformTransferRequest(TransactionCase):
    """يتحقق من خط سير طلب نقل الموظف بين المنصات - النقل لم يعد ينفَّذ
    فوراً بضغطة واحدة، بل يمر بموافقتين: مسؤول المنصة الحالية للموظف
    تحديداً، ثم مدير العمليات (وينفّذ النقل الفعلي عند نفس ضغطته)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env['hr.employee']
        cls.Request = cls.env['hr.employee.platform.transfer.request']
        cls.pm_group = cls.env.ref('recruitment_workflow.group_recruitment_workflow_project_manager')
        cls.ops_group = cls.env.ref('recruitment_workflow.group_recruitment_workflow_operations')
        cls.current_project = cls.env['project.project'].create({'name': 'المنصة الحالية - طلب نقل'})
        cls.new_project = cls.env['project.project'].create({'name': 'المنصة الجديدة - طلب نقل'})
        cls.current_pm = cls.env['res.users'].create({
            'name': 'مسؤول المنصة الحالية - طلب نقل',
            'login': 'transfer_current_pm',
            'email': 'transfer_current_pm@example.com',
            'group_ids': [(6, 0, [cls.pm_group.id, cls.env.ref('base.group_user').id])],
        })
        cls.other_pm = cls.env['res.users'].create({
            'name': 'مسؤول مشروع آخر - طلب نقل',
            'login': 'transfer_other_pm',
            'email': 'transfer_other_pm@example.com',
            'group_ids': [(6, 0, [cls.pm_group.id, cls.env.ref('base.group_user').id])],
        })
        cls.ops_user = cls.env['res.users'].create({
            'name': 'مدير العمليات - طلب نقل',
            'login': 'transfer_ops_user',
            'email': 'transfer_ops_user@example.com',
            'group_ids': [(6, 0, [cls.ops_group.id, cls.env.ref('base.group_user').id])],
        })
        cls.current_project.user_id = cls.current_pm

    def _create_request(self, employee):
        return self.Request.create({
            'employee_id': employee.id,
            'new_project_id': self.new_project.id,
        })

    def test_direct_write_to_employee_project_id_blocked(self):
        """المنصة الحالية على سجل الموظف نفسه لا يجوز تعديلها مباشرة (شاشة
        الموظف، تعديل جماعي، استيراد، أو RPC) - وإلا فُطلب نقل المنصة بخط
        سير الموافقة بالكامل يصبح بلا معنى، يكفي فتح سجل الموظف وتغيير
        الحقل يدوياً لتجاوزه تماماً."""
        employee = self.Employee.create({'name': 'موظف - قفل المنصة المباشر', 'project_id': self.current_project.id})

        with self.assertRaises(UserError):
            employee.write({'project_id': self.new_project.id})
        with self.assertRaises(UserError):
            employee.project_id = self.new_project.id

    def test_full_approval_flow_executes_transfer_with_selected_date(self):
        """المسار الكامل: مسودة ← بانتظار الموافقة ← وافق مسؤول المنصة
        الحالية ← تم النقل - وباستخدام تاريخ النقل الذي يحدّده المستخدم
        فعلياً، لا تاريخ اليوم دائماً."""
        employee = self.Employee.create({'name': 'موظف للنقل', 'project_id': self.current_project.id})
        past_date = date.today() - timedelta(days=30)
        request = self._create_request(employee)
        request.transfer_date = past_date
        self.assertEqual(request.current_project_id, self.current_project)

        request.action_submit_review()
        self.assertEqual(request.state, 'waiting_approval')

        request.with_user(self.current_pm).action_pm_approve()
        self.assertEqual(request.state, 'pm_approved')

        request.with_user(self.ops_user).action_confirm_transfer()
        self.assertEqual(request.state, 'done')
        self.assertEqual(employee.project_id, self.new_project)
        self.assertEqual(employee.platform_history_ids.filtered('is_current').date_start, past_date)

    def test_pm_approve_requires_specific_current_platform_manager(self):
        """الموافقة تتطلب مسؤول المنصة الحالية للموظف تحديداً - وليس أي
        عضو آخر في مجموعة مسؤولي المشاريع."""
        employee = self.Employee.create({'name': 'موظف للنقل 2', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.with_user(self.other_pm).action_pm_approve()

        request.with_user(self.current_pm).action_pm_approve()
        self.assertEqual(request.state, 'pm_approved')

    def test_pm_approve_falls_back_to_operations_without_assigned_manager(self):
        """موظف على منصة بلا مسؤول معيّن (أو بلا منصة أصلاً) - يُكتفى
        بصلاحية مدير العمليات كحل احتياطي بدل تعطّل الطلب."""
        employee = self.Employee.create({'name': 'موظف بلا منصة'})
        request = self._create_request(employee)
        self.assertFalse(request.current_project_id)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.with_user(self.other_pm).action_pm_approve()

        request.with_user(self.ops_user).action_pm_approve()
        self.assertEqual(request.state, 'pm_approved')

    def test_confirm_transfer_requires_pm_approval_first(self):
        employee = self.Employee.create({'name': 'موظف للنقل 3', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.with_user(self.ops_user).action_confirm_transfer()

    def test_fields_locked_immediately_after_submit_review(self):
        """القفل يبدأ فور "إرسال للمراجعة" مباشرة - قبل أي موافقة."""
        employee = self.Employee.create({'name': 'موظف للنقل 4', 'project_id': self.current_project.id})
        other_employee = self.Employee.create({'name': 'موظف آخر'})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.write({'employee_id': other_employee.id})
        with self.assertRaises(UserError):
            request.write({'new_project_id': self.current_project.id})

    def test_confirm_transfer_blocked_if_current_platform_changed_since_request(self):
        """حارس ضد لقطة قديمة: إن تغيّرت المنصة الحالية للموظف فعلياً منذ
        إنشاء الطلب (نُقل عبر طلب آخر أولاً) - يُرفض التنفيذ برسالة واضحة
        بدل تنفيذ نقل مبني على بيانات لم تعد صحيحة."""
        employee = self.Employee.create({'name': 'موظف للنقل 5', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()
        request.with_user(self.current_pm).action_pm_approve()

        # يُنقَل الموظف فعلياً لمنصة أخرى عبر مسار مختلف بينما هذا الطلب
        # لا يزال معلَّقاً في حالة "وافق مسؤول المنصة الحالية".
        third_project = self.env['project.project'].create({'name': 'منصة ثالثة'})
        employee._open_platform_history(third_project)

        with self.assertRaises(UserError):
            request.with_user(self.ops_user).action_confirm_transfer()

    def test_reset_draft_and_cancel_require_operations_group(self):
        employee = self.Employee.create({'name': 'موظف للنقل 6', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.with_user(self.current_pm).action_reset_draft(reason='اختبار')
        with self.assertRaises(UserError):
            request.with_user(self.current_pm).action_cancel()

        request.with_user(self.ops_user).action_reset_draft(reason='بيانات خاطئة')
        self.assertEqual(request.state, 'draft')

    def test_reset_draft_requires_reason(self):
        """الإرجاع لمسودة يفرض تسجيل سبب - نفس مبدأ "إرجاع للتصحيح" في
        سير طلبات التوظيف (recruitment.return.wizard)."""
        employee = self.Employee.create({'name': 'موظف للنقل 8', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.with_user(self.ops_user).action_reset_draft()

        message_count_before = len(request.message_ids)
        request.with_user(self.ops_user).action_reset_draft(reason='سبب واضح')
        self.assertEqual(request.state, 'draft')
        self.assertGreater(len(request.message_ids), message_count_before)

    def test_reset_to_draft_blocked_via_direct_write(self):
        """الإرجاع لمسودة ممنوع مباشرة (نقر على شريط الحالة أو write() عبر
        RPC) - يجب أن يمر حصراً عبر معالج الإرجاع الذي يفرض السبب."""
        employee = self.Employee.create({'name': 'موظف للنقل 9', 'project_id': self.current_project.id})
        request = self._create_request(employee)
        request.action_submit_review()

        with self.assertRaises(UserError):
            request.write({'state': 'draft'})

    def test_state_jump_more_than_one_step_blocked(self):
        """لا يجوز القفز عدة مراحل دفعة واحدة عبر write() مباشر (مثلاً
        النقر على فقاعة متقدمة في شريط الحالة) - حتى لو استُوفيت الشروط
        الوسيطة تقنياً."""
        employee = self.Employee.create({'name': 'موظف للنقل 10', 'project_id': self.current_project.id})
        request = self._create_request(employee)

        with self.assertRaises(UserError):
            request.write({'state': 'pm_approved'})

    def test_activity_scheduled_for_current_pm_on_submit(self):
        """عند "إرسال للمراجعة"، يُجدوَل تنبيه (Activity) تلقائي لمسؤول
        المنصة الحالية تحديداً - بدل تركه يكتشف الطلب بالصدفة."""
        employee = self.Employee.create({'name': 'موظف للنقل 11', 'project_id': self.current_project.id})
        request = self._create_request(employee)

        request.action_submit_review()

        self.assertTrue(request.activity_ids)
        self.assertEqual(request.activity_ids[:1].user_id, self.current_pm)

    def test_same_project_rejected(self):
        """لا يجوز إنشاء طلب نقل لنفس المنصة الحالية للموظف."""
        employee = self.Employee.create({'name': 'موظف للنقل 7', 'project_id': self.current_project.id})
        with self.assertRaises(UserError):
            self.Request.create({
                'employee_id': employee.id,
                'new_project_id': self.current_project.id,
            })
