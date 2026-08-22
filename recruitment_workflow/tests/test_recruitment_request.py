# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestRecruitmentRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env['recruitment.request']
        cls.stage_project_review = cls.env.ref('recruitment_workflow.stage_project_review')
        cls.stage_operations_review = cls.env.ref('recruitment_workflow.stage_operations_review')
        cls.stage_sponsorship_transfer = cls.env.ref('recruitment_workflow.stage_sponsorship_transfer')
        cls.group_pm = cls.env.ref('recruitment_workflow.group_recruitment_workflow_project_manager')
        cls.group_ops = cls.env.ref('recruitment_workflow.group_recruitment_workflow_operations')
        cls.group_manager = cls.env.ref('recruitment_workflow.group_recruitment_workflow_manager')

    def _create_request(self, **kwargs):
        vals = {
            'employee_name': 'موظف تجريبي',
            'identification_id': '1234567890',
            'mobile': '0501234567',
            'email': 'test.request@example.com',
        }
        vals.update(kwargs)
        return self.Request.create(vals)

    def _complete_gov_fee_for_request(self, request):
        """يُكمل سجل "الرسوم الحكومية" في bank_settlement (إن كان الموديول
        مثبَّتاً ضمن هذه الدفعة من الاختبارات) إلى حالة "منفّذة" - اختصار
        لأغراض الاختبار فقط عبر sudo() المباشر (يتجاوز خط سير موافقة
        bank_settlement بالكامل عمداً)، وليس recruitment_workflow نفسه لا
        يعتمد على bank_settlement أصلاً (العكس صحيح) فلا توجد طريقة
        "رسمية" هنا لإكماله. ضروري لأي اختبار يحتاج مغادرة مرحلة "تم
        السداد" بنجاح فعلي: bank_settlement.recruitment_request._validate
        _stage_exit تضيف شرطاً أعمق (تسجيل+تنفيذ الرسوم الحكومية فعلياً)
        فوق شرط recruitment_workflow الأساسي (وجود مبلغ فقط) متى ما كان
        gov_fee_amount > 0 - فمجرد ضبط المبلغ وحده لا يكفي عملياً."""
        if 'bank_settlement_gov_fee_id' not in request._fields:
            return  # bank_settlement غير مثبَّت في هذا السياق
        if not request.bank_settlement_gov_fee_id:
            request.action_register_gov_fee()
        request.bank_settlement_gov_fee_id.sudo().write({'state': 'done'})

    # ------------------------------------------------------------------
    # التحقق من صحة البيانات (identification_id / mobile)
    # ------------------------------------------------------------------
    def test_identification_id_must_be_digits(self):
        with self.assertRaises(ValidationError):
            self._create_request(identification_id='12A4567890')

    def test_identification_id_must_be_10_digits(self):
        with self.assertRaises(ValidationError):
            self._create_request(identification_id='12345')

    def test_identification_id_must_start_with_1_or_2(self):
        with self.assertRaises(ValidationError):
            self._create_request(identification_id='3123456789')

    def test_identification_id_valid_passes(self):
        request = self._create_request(identification_id='2123456780')
        self.assertTrue(request)

    def test_mobile_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_request(identification_id='1123456781', mobile='0123456789')

    def test_mobile_valid_formats_pass(self):
        for i, mobile in enumerate(['0501234567', '966501234567', '+966501234567']):
            request = self._create_request(
                identification_id='11111111%02d' % (i + 10), mobile=mobile,
            )
            self.assertTrue(request)

    def test_identification_id_uniqueness(self):
        self._create_request(identification_id='1234567890', email='a@example.com')
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._create_request(identification_id='1234567890', email='b@example.com')

    def test_identification_id_uniqueness_across_companies(self):
        """رقم الهوية يمثّل شخصاً حقيقياً واحداً - يجب أن يُمنع تكراره حتى
        عبر شركات مختلفة، وليس فقط داخل نفس الشركة."""
        other_company = self.env['res.company'].create({'name': 'شركة تجريبية للتكرار'})
        self._create_request(identification_id='1234567816', email='z1@example.com')
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._create_request(
                identification_id='1234567816', email='z2@example.com',
                company_id=other_company.id,
            )

    def test_stage_cannot_be_deleted_while_in_use(self):
        """حذف مرحلة مرتبطة بطلبات فعلية يجب أن يُمنع تماماً (ondelete=
        restrict) - وليس تفريغ حقل المرحلة بصمت، وهو ما كان يُسقط فحص
        صلاحيات الموافقة بالكامل عن الطلبات المتأثرة."""
        stage = self.env['recruitment.stage'].create({
            'name': 'مرحلة تجريبية للحذف', 'code': 'test_delete_stage',
        })
        request = self._create_request(identification_id='1123456784', email='x@example.com')
        request.with_context(skip_stage_validation=True).write({'stage_id': stage.id})

        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            stage.unlink()

    def test_request_cannot_be_deleted_even_by_manager(self):
        """طلبات التوظيف سجل تدقيق دائم - يُمنع حذفها نهائياً حتى لمن يملك
        صلاحية الحذف على مستوى ir.model.access (مدير سير العمل كامل
        الصلاحيات)؛ الأرشفة هي البديل الوحيد."""
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(identification_id='1123456785', email='y@example.com')

        with self.assertRaises(UserError):
            request.unlink()

    def test_short_national_address_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_request(
                identification_id='1123456782', short_national_address='1234RRRD',
            )

    def test_short_national_address_valid_passes(self):
        request = self._create_request(
            identification_id='1123456783', short_national_address='RRRD2929',
        )
        self.assertTrue(request)

    # ------------------------------------------------------------------
    # اشتقاق الشركة من المشروع المختار (Multi-Company)
    # ------------------------------------------------------------------
    def test_company_synced_from_project_onchange(self):
        """عند اختيار المشروع، تُشتَق الشركة تلقائياً من شركة ذلك المشروع -
        ولا تتغيّر إلا بتغيير المشروع نفسه."""
        # حقل company_id مقيَّد بـgroups="base.group_multi_company" في
        # الواجهة - بدون هذه المجموعة لن يظهر الحقل أصلاً في Form ويفشل
        # الاختبار بخطأ "حقل غير معروف". لكن ذلك وحده غير كافٍ: فلترة
        # المجموعات على مستوى الحقل تُدمَج (AND) مع مجموعات ir.model.access
        # الخاصة بالنموذج نفسها - فلا بد أيضاً من مجموعة تملك حق قراءة
        # recruitment.request أصلاً (group_pm هنا)، وإلا يبقى الحقل مخفياً
        # رغم امتلاك base.group_multi_company.
        self.env.user.write({
            'group_ids': [
                (4, self.env.ref('base.group_multi_company').id),
                (4, self.group_pm.id),
            ],
        })
        other_company = self.env['res.company'].create({'name': 'شركة تجريبية أخرى'})
        project = self.env['project.project'].create({
            'name': 'منصة شركة أخرى', 'company_id': other_company.id,
        })
        with Form(self.Request) as form:
            form.employee_name = 'موظف تجريبي'
            form.identification_id = '1234567898'
            form.mobile = '0501234567'
            form.email = 'company-sync@example.com'
            form.project_id = project
            self.assertEqual(form.company_id, other_company)
        request = form.save()
        self.assertEqual(request.company_id, other_company)

    def test_company_and_pm_derived_on_direct_create_without_onchange(self):
        """create() المباشر (كما يفعل تحكم تسجيل الموقع الإلكتروني العام،
        الذي لا يمر بنموذج الواجهة ولا يستدعي onchange إطلاقاً) يجب أن
        يشتق الشركة ومسؤول المشروع من المشروع نفسه أيضاً - وليس فقط
        الإنشاء عبر Form. هذا كان يسبب ربط طلبات الموقع بشركة المستخدم/
        الموقع الحالية بدل شركة المشروع الفعلية."""
        other_company = self.env['res.company'].create({'name': 'شركة تجريبية ثانية'})
        pm_user = self.env['res.users'].create({
            'name': 'مسؤول مشروع للموقع', 'login': 'website_pm_user',
            'email': 'website_pm_user@example.com',
        })
        project = self.env['project.project'].create({
            'name': 'منصة تسجيل الموقع', 'company_id': other_company.id, 'user_id': pm_user.id,
        })

        request = self.Request.create({
            'employee_name': 'مرشّح من الموقع',
            'identification_id': '1234567810',
            'mobile': '0501234567',
            'email': 'website-candidate@example.com',
            'project_id': project.id,
        })

        self.assertEqual(request.company_id, other_company)
        self.assertEqual(request.project_manager_id, pm_user)

    def test_department_derived_directly_from_project_over_job(self):
        """قسم المشروع المباشر (project.department_id) له الأولوية دائماً
        على قسم الوظيفة الافتراضية عند اشتقاق قسم الطلب."""
        department_direct = self.env['hr.department'].create({'name': 'قسم مباشر على المشروع'})
        department_via_job = self.env['hr.department'].create({'name': 'قسم عبر الوظيفة'})
        job = self.env['hr.job'].create({
            'name': 'وظيفة تجريبية', 'department_id': department_via_job.id,
        })
        project = self.env['project.project'].create({
            'name': 'منصة بقسم مباشر',
            'department_id': department_direct.id,
            'default_job_id': job.id,
        })

        request = self.Request.create({
            'employee_name': 'مرشّح لاختبار القسم',
            'identification_id': '1234567814',
            'mobile': '0501234567',
            'email': 'department-test@example.com',
            'project_id': project.id,
        })

        self.assertEqual(request.department_id, department_direct)

    def test_department_falls_back_to_job_department_without_direct_one(self):
        """بدون قسم مباشر على المشروع، يُشتق القسم من قسم الوظيفة
        الافتراضية كما كان سابقاً."""
        department_via_job = self.env['hr.department'].create({'name': 'قسم عبر الوظيفة فقط'})
        job = self.env['hr.job'].create({
            'name': 'وظيفة تجريبية 2', 'department_id': department_via_job.id,
        })
        project = self.env['project.project'].create({
            'name': 'منصة بدون قسم مباشر', 'default_job_id': job.id,
        })

        request = self.Request.create({
            'employee_name': 'مرشّح لاختبار القسم 2',
            'identification_id': '1234567815',
            'mobile': '0501234567',
            'email': 'department-test-2@example.com',
            'project_id': project.id,
        })

        self.assertEqual(request.department_id, department_via_job)

    def test_company_and_pm_derived_on_write_without_onchange(self):
        """نفس الاشتقاق مطلوب أيضاً عند write() لتغيير project_id على طلب
        موجود، وليس فقط create() - حتى لو أرسل المتصفح project_id فقط
        بمعزل عن company_id/project_manager_id (حقول readonly قد لا
        يرسلها المتصفح ضمن قيم الحفظ رغم تحديثها بصرياً عبر onchange)."""
        other_company = self.env['res.company'].create({'name': 'شركة تجريبية ثالثة'})
        pm_user = self.env['res.users'].create({
            'name': 'مسؤول مشروع لتعديل الطلب', 'login': 'write_pm_user',
            'email': 'write_pm_user@example.com',
        })
        project = self.env['project.project'].create({
            'name': 'منصة تعديل الطلب', 'company_id': other_company.id, 'user_id': pm_user.id,
        })
        request = self._create_request(identification_id='1234567811', email='u@example.com')

        request.write({'project_id': project.id})

        self.assertEqual(request.company_id, other_company)
        self.assertEqual(request.project_manager_id, pm_user)

    # ------------------------------------------------------------------
    # إغلاق ثغرة تجاوز المراحل عبر write() المباشر على stage_id
    # ------------------------------------------------------------------
    def test_write_stage_multi_step_skip_blocked(self):
        """لا يُسمح بالقفز أكثر من مرحلة واحدة دفعة واحدة عبر write() مباشر
        (مثلاً بالضغط على فقاعة متقدمة في شريط الحالة القابل للنقر) - حتى لو
        كان المستخدم يملك كل صلاحيات الموافقة (مدير سير العمل) وكانت كل
        الشروط الوسيطة مستوفاة تقنياً. الانتقال يجب أن يمر خطوة بخطوة عبر
        الأزرار الصريحة."""
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية'})
        request = self._create_request(project_id=project.id)
        request.attachment_line_ids.write({'file': b'ZmFrZQ=='})
        self.assertTrue(request.attachments_complete)

        with self.assertRaises(UserError):
            request.write({'stage_id': self.stage_operations_review.id})

    def test_write_stage_single_step_blocked_without_approval_rights(self):
        """انتقال خطوة واحدة فقط (المرحلة التالية مباشرة) من مرحلة تتطلب
        موافقة ('project_review') لا يزال يتطلب صلاحية الموافقة عليها -
        المستخدم الحالي (superuser بدون مجموعات مخصصة) لا يملكها.

        user_id=False صراحة على المشروع: بدونها project.project.user_id
        يُشتق تلقائياً لمن أنشأه (المستخدم الحالي نفسه)، فيصبح هو "مسؤول
        المشروع المعيّن" تلقائياً ويملك الصلاحية بالخطأ - يُبطل الاختبار."""
        project = self.env['project.project'].create({
            'name': 'منصة تجريبية 2', 'user_id': False,
        })
        request = self._create_request(
            identification_id='1234567891', email='c@example.com', project_id=project.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })
        next_stage = request._next_stage()
        self.assertEqual(next_stage, self.stage_operations_review)

        with self.assertRaises(UserError):
            request.write({'stage_id': next_stage.id})

    def test_write_stage_paid_free_without_fee_move(self):
        """مغادرة مرحلة "تم السداد" لا تفرض أي شرط متعلق بآلية "رسوم
        التوظيف" الخارجية القديمة (fee_amount/fee_move_id/action_create_
        fee_bill) - أُزيل الزر والحقول من كل الشاشات نهائياً، وأُزيل معه
        هذا التحقق البرمجي أيضاً (كان يعلّق أي طلب له قيمة قديمة في
        fee_amount للأبد، يطلب زراً لم يعد موجوداً إطلاقاً - ثغرة حقيقية
        اكتُشفت من شكوى مستخدم فعلية). الشرط الفعلي الوحيد المتبقي مرتبط
        بالرسوم الحكومية (gov_fee_amount) في مرحلة "جاري نقل الكفالة"."""
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية 3'})
        request = self._create_request(
            identification_id='1234567895', email='g@example.com', project_id=project.id,
            fee_amount=500.0, gov_fee_amount=1000.0,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_paid').id,
        })
        self._complete_gov_fee_for_request(request)

        request.write({'stage_id': self.stage_sponsorship_transfer.id})
        self.assertEqual(request.stage_id.code, 'sponsorship_transfer')

    # ------------------------------------------------------------------
    # الإرجاع لمرحلة سابقة مسموح فقط عبر معالج "إرجاع للتصحيح"
    # ------------------------------------------------------------------
    def test_write_stage_backward_blocked_without_wizard(self):
        """النقر على فقاعة مرحلة سابقة في شريط الحالة القابل للنقر (أو أي
        write() مباشر آخر) لا يجب أن يُرجع الطلب مباشرة - الإرجاع مسموح فقط
        عبر action_return_to_stage (معالج "إرجاع للتصحيح") الذي يفرض تسجيل
        السبب."""
        project = self.env['project.project'].create({'name': 'منصة تجريبية 4'})
        request = self._create_request(
            identification_id='1234567893', email='e@example.com', project_id=project.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_operations_review.id,
        })

        with self.assertRaises(UserError):
            request.write({'stage_id': self.stage_project_review.id})

    def test_action_return_to_stage_still_works(self):
        """المسار الرسمي (معالج الإرجاع) يبقى يعمل رغم حظر الكتابة المباشرة
        للخلف - لأنه يستخدم سياق skip_stage_validation عمداً."""
        project = self.env['project.project'].create({'name': 'منصة تجريبية 5'})
        request = self._create_request(
            identification_id='1234567894', email='f@example.com', project_id=project.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_operations_review.id,
        })

        request.action_return_to_stage(self.stage_project_review, 'بيانات ناقصة')
        self.assertEqual(request.stage_id, self.stage_project_review)

    # ------------------------------------------------------------------
    # التحقق من تطبيق صلاحيات الموافقة الهرمية عبر action_approve
    # ------------------------------------------------------------------
    def test_approval_rights_hierarchy(self):
        pm_user = self.env['res.users'].create({
            'name': 'مسؤول مشروع تجريبي',
            'login': 'pm_test_user',
            'email': 'pm_test_user@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        # user_id=False صراحة: بدونها يُشتق تلقائياً لمنشئ المشروع (المستخدم
        # الحالي هنا، وليس pm_user) فيصبح هو "المعيّن تحديداً" بدل أن يُعتمد
        # على فحص المجموعة العام كما يفترضه هذا الاختبار.
        project = self.env['project.project'].create({
            'name': 'منصة تجريبية 3', 'user_id': False,
        })
        request = self._create_request(
            identification_id='1234567892', email='d@example.com', project_id=project.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })

        # مسؤول المشروع يستطيع الموافقة على مرحلته الخاصة
        request.with_user(pm_user).action_approve()
        self.assertEqual(request.stage_id, self.stage_operations_review)

        # لكنه لا يملك صلاحية الموافقة على مرحلة مدير العمليات
        with self.assertRaises(UserError):
            request.with_user(pm_user).action_approve()

    def test_project_review_requires_specific_assigned_manager(self):
        """عند تعيين مسؤول مشروع محدّد على الطلب، الموافقة على مرحلة
        "قيد المراجعة" يجب أن تقتصر عليه هو تحديداً - حتى لو كان مستخدم آخر
        عضواً في نفس مجموعة "مسؤول المشروع" (أو حتى مديراً كامل الصلاحيات)."""
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول المشروع المعيّن',
            'login': 'assigned_pm_user',
            'email': 'assigned_pm_user@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع آخر',
            'login': 'other_pm_user',
            'email': 'other_pm_user@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({'name': 'منصة تجريبية 4'})
        request = self._create_request(
            identification_id='1234567896', email='h@example.com',
            project_id=project.id, project_manager_id=assigned_pm.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })

        # مسؤول مشروع آخر (نفس المجموعة) لا يستطيع الموافقة
        with self.assertRaises(UserError):
            request.with_user(other_pm).action_approve()

        # حتى المدير كامل الصلاحيات لا يستطيع - المطلوب الشخص المعيّن تحديداً
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        with self.assertRaises(UserError):
            request.action_approve()

        # المسؤول المعيّن تحديداً يستطيع
        request.with_user(assigned_pm).action_approve()
        self.assertEqual(request.stage_id, self.stage_operations_review)

    def test_stage_activity_notifies_specific_assigned_manager(self):
        """إشعار مرحلة "قيد المراجعة" كان يصل لأول عضو عشوائي بمجموعة
        "مسؤول المشروع" ككل - وليس مسؤول المشروع المحدَّد تحديداً على
        هذا الطلب بالذات (الشخص الوحيد المخوَّل فعلياً بالموافقة عليه) -
        ثغرة حقيقية: قد لا يصل الإشعار أبداً لمن يملك صلاحية الموافقة."""
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول المشروع المعيّن - إشعار',
            'login': 'assigned_pm_notify_user',
            'email': 'assigned_pm_notify_user@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع آخر - إشعار',
            'login': 'other_pm_notify_user',
            'email': 'other_pm_notify_user@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({'name': 'منصة تجريبية - إشعار'})
        request = self._create_request(
            identification_id='1234567897', email='i@example.com',
            project_id=project.id, project_manager_id=assigned_pm.id,
        )

        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })

        self.assertTrue(request.activity_ids)
        self.assertEqual(request.activity_ids[:1].user_id, assigned_pm)
        self.assertNotEqual(request.activity_ids[:1].user_id, other_pm)

    # ------------------------------------------------------------------
    # أفعال حساسة أخرى يجب أن تتحقق من الصلاحية من جهة الخادم أيضاً
    # (وليس فقط عبر إخفاء الأزرار في الواجهة) - action_reject,
    # action_reset_to_draft, action_unarchive_request مقيّدة بمجموعة
    # "مدير العمليات" في الواجهة.
    # ------------------------------------------------------------------
    def _create_plain_user(self, login):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            'group_ids': [(6, 0, [self.env.ref('recruitment_workflow.group_recruitment_workflow_user').id,
                                   self.env.ref('base.group_user').id])],
        })

    def test_action_reject_requires_operations_group(self):
        plain_user = self._create_plain_user('reject_test_user')
        request = self._create_request(identification_id='1234567896', email='h@example.com')

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_reject(reason='سبب تجريبي')

    def test_leaving_paid_stage_requires_operations_group(self):
        """مغادرة مرحلة "تم السداد" تتطلب مدير العمليات فما فوق - لا يكفي
        أن يكون المستخدم من مستخدمي التطبيق الأساسيين فقط."""
        plain_user = self._create_plain_user('paid_stage_test_user')
        request = self._create_request(
            identification_id='1234567897', email='paidstage@example.com',
            gov_fee_amount=1000.0,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_paid').id,
        })

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_next_stage()

        self.env.user.write({'group_ids': [(4, self.group_ops.id)]})
        self._complete_gov_fee_for_request(request)
        request.action_next_stage()
        self.assertEqual(request.stage_id.code, 'sponsorship_transfer')

    def test_paid_stage_exit_requires_gov_fee_amount(self):
        """طلب صريح: لا يمكن مغادرة مرحلة "تم السداد" بمبلغ رسوم حكومية
        صفري/فارغ - كان بالإمكان تجاوزها بلا أي مبلغ محدَّد، وهو ما لا
        معنى له (كل طلب توظيف حقيقي يترتب عليه رسوم حكومية لنقل الكفالة)."""
        self.env.user.write({'group_ids': [(4, self.group_ops.id)]})
        request = self._create_request(identification_id='1234567844', email='an@example.com')
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_paid').id,
        })

        with self.assertRaises(UserError):
            request.action_next_stage()

        request.gov_fee_amount = 1500.0
        self._complete_gov_fee_for_request(request)
        request.action_next_stage()
        self.assertEqual(request.stage_id.code, 'sponsorship_transfer')

    def test_action_reject_allowed_for_assigned_project_manager_at_new_only(self):
        """مسؤول المشروع المعيّن تحديداً يستطيع الرفض من المرحلة الأولى فقط
        (قبل رفع المرفقات) - ليس من أي مرحلة أخرى، وليس مسؤول مشروع آخر غير
        معيّن على هذا الطلب."""
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع معيّن للرفض',
            'login': 'reject_assigned_pm',
            'email': 'reject_assigned_pm@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع آخر للرفض',
            'login': 'reject_other_pm',
            'email': 'reject_other_pm@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({'name': 'منصة تجريبية 9'})
        request = self._create_request(
            identification_id='1234567808', email='s@example.com',
            project_id=project.id, project_manager_id=assigned_pm.id,
        )
        self.assertEqual(request.stage_id.code, 'new')

        # مسؤول مشروع آخر (نفس المجموعة لكن غير معيّن) لا يستطيع
        with self.assertRaises(UserError):
            request.with_user(other_pm).action_reject(reason='سبب تجريبي')

        # المعيّن تحديداً يستطيع من المرحلة الأولى
        request.with_user(assigned_pm).action_reject(reason='لا يستوفي الشروط')
        self.assertEqual(request.state, 'rejected')

    def test_action_reject_blocked_for_project_manager_past_new_stage(self):
        """مسؤول المشروع المعيّن لا يستطيع الرفض بعد تجاوز المرحلة الأولى -
        الرفض من مراحل الموافقة اللاحقة يبقى حصراً لمدير العمليات."""
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع معيّن للرفض 2',
            'login': 'reject_assigned_pm_2',
            'email': 'reject_assigned_pm_2@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({'name': 'منصة تجريبية 10'})
        request = self._create_request(
            identification_id='1234567809', email='t@example.com',
            project_id=project.id, project_manager_id=assigned_pm.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })

        with self.assertRaises(UserError):
            request.with_user(assigned_pm).action_reject(reason='سبب تجريبي')

    def test_action_reject_allowed_for_hr_at_sponsorship_stages(self):
        """الموارد البشرية تستطيع رفض الطلب من مرحلتي نقل الكفالة تحديداً -
        يغطي حالة رفض الموظف نفسه لنقل الكفالة فعلياً."""
        hr_user = self._create_plain_user('reject_hr_user')
        hr_user.write({
            'group_ids': [(4, self.env.ref('recruitment_workflow.group_recruitment_workflow_hr').id)],
        })
        request = self._create_request(identification_id='1234567810', email='u2@example.com')
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_sponsorship_transfer.id,
        })

        request.with_user(hr_user).action_reject(reason='رفض الموظف نقل الكفالة')

        self.assertEqual(request.state, 'rejected')

    def test_action_reject_blocked_for_hr_outside_sponsorship_stages(self):
        """الموارد البشرية لا تستطيع الرفض من مراحل أخرى غير مرحلتي نقل
        الكفالة."""
        hr_user = self._create_plain_user('reject_hr_user_2')
        hr_user.write({
            'group_ids': [(4, self.env.ref('recruitment_workflow.group_recruitment_workflow_hr').id)],
        })
        request = self._create_request(identification_id='1234567811', email='u3@example.com')
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_project_review.id,
        })

        with self.assertRaises(UserError):
            request.with_user(hr_user).action_reject(reason='سبب تجريبي')

    def test_action_return_to_stage_requires_operations_group(self):
        """إرجاع الطلب لمرحلة سابقة كان بدون أي تقييد صلاحية على الإطلاق -
        أي مستخدم أساسي يستطيع إرجاع أي طلب. يجب أن يقتصر على مدير العمليات
        فما فوق، أو مسؤول المشروع المعيّن تحديداً على هذا الطلب (انظر
        الاختبار التالي) - وليس أي مستخدم أساسي."""
        plain_user = self._create_plain_user('return_stage_test_user')
        project = self.env['project.project'].create({'name': 'منصة تجريبية 7'})
        request = self._create_request(
            identification_id='1234567806', email='q@example.com', project_id=project.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_operations_review.id,
        })

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_return_to_stage(
                self.stage_project_review, 'سبب تجريبي',
            )

    def test_action_return_to_stage_allowed_for_assigned_project_manager(self):
        """مسؤول المشروع المعيّن تحديداً على الطلب يستطيع إرجاعه للتصحيح
        (مثلاً لطلب وثائق ناقصة من المرشّح) حتى لو لم يكن مديراً للعمليات -
        لكن مسؤول مشروع آخر غير معيّن على هذا الطلب بالذات لا يستطيع."""
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع معيّن للإرجاع',
            'login': 'return_assigned_pm',
            'email': 'return_assigned_pm@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع آخر للإرجاع',
            'login': 'return_other_pm',
            'email': 'return_other_pm@example.com',
            'group_ids': [(6, 0, [self.group_pm.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({'name': 'منصة تجريبية 8'})
        request = self._create_request(
            identification_id='1234567807', email='r@example.com',
            project_id=project.id, project_manager_id=assigned_pm.id,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_operations_review.id,
        })

        with self.assertRaises(UserError):
            request.with_user(other_pm).action_return_to_stage(
                self.stage_project_review, 'سبب تجريبي',
            )

        request.with_user(assigned_pm).action_return_to_stage(
            self.stage_project_review, 'وثائق ناقصة - يرجى إعادة الرفع',
        )
        self.assertEqual(request.stage_id, self.stage_project_review)

    def test_action_reset_to_draft_requires_operations_group(self):
        plain_user = self._create_plain_user('reset_test_user')
        request = self._create_request(identification_id='1234567897', email='i@example.com')
        request.write({'state': 'rejected', 'active': False})

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_reset_to_draft()

    def test_action_unarchive_request_requires_operations_group(self):
        plain_user = self._create_plain_user('unarchive_test_user')
        request = self._create_request(identification_id='1234567898', email='j@example.com')
        request.active = False

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_unarchive_request()

    def test_car_request_stage_exit_requires_project_manager(self):
        """إنهاء مرحلة "طلب سيارة" (بعد تفويض الأسطول) يجب أن يبقى حصراً
        لمسؤول المشروع، حتى عند استدعاء action_next_stage مباشرة."""
        plain_user = self._create_plain_user('car_finish_test_user')
        project = self.env['project.project'].create({'name': 'منصة تجريبية 6'})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة تجريبية'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل تجريبي', 'brand_id': brand.id,
        })
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': model.id,
            'recruitment_state': 'assigned',
        })
        request = self._create_request(
            identification_id='1234567899', email='k@example.com', project_id=project.id,
            vehicle_id=vehicle.id, car_request_state='authorized',
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_car_request').id,
        })

        with self.assertRaises(UserError):
            request.with_user(plain_user).action_next_stage()

    # ------------------------------------------------------------------
    # حماية project_manager_id + مزامنة تعديل المشروع مع الطلبات الجارية
    # ------------------------------------------------------------------
    def test_project_manager_id_cannot_be_written_alone(self):
        """لا يمكن تعديل project_manager_id مباشرة بمعزل عن project_id -
        هذا كان يسمح بانتحال هوية مسؤول المشروع المخصّص لموافقة معيّنة."""
        other_pm = self.env['res.users'].create({
            'name': 'مسؤول آخر', 'login': 'direct_write_pm', 'email': 'direct_write_pm@example.com',
        })
        request = self._create_request(identification_id='1234567801', email='l@example.com')

        with self.assertRaises(UserError):
            request.write({'project_manager_id': other_pm.id})

    def test_company_id_cannot_be_written_alone(self):
        """لا يمكن تعديل company_id مباشرة بمعزل عن project_id - ثغرة
        حقيقية اكتُشفت بمراجعة شاملة (تدقيق صلاحيات Studio): كان الحقل
        readonly="1" في الشاشة فقط (تسهيل واجهة)، بلا أي حماية فعلية من
        جهة الخادم - تعديله مباشرة (RPC، أو بعد إزالة قيد الواجهة عبر
        Studio) كان يغيّر فرع/شركة الطلب بمعزل عن المشروع الفعلي المختار،
        رغم اشتقاقه تلقائياً منه حصراً (نفس منطق project_manager_id
        تماماً أعلاه)."""
        other_company = self.env['res.company'].create({'name': 'شركة أخرى - قفل الشركة'})
        request = self._create_request(identification_id='1234567848', email='ar@example.com')

        with self.assertRaises(UserError):
            request.write({'company_id': other_company.id})

    def test_project_edit_syncs_only_in_progress_requests(self):
        """تعديل "مسؤول المشروع" على المشروع نفسه ينعكس تلقائياً على الطلبات
        التي لا تزال قيد التنفيذ فقط - الطلبات المكتملة تحتفظ بالقيمة القديمة
        كسجل تاريخي لا يتغيّر."""
        original_pm = self.env['res.users'].create({
            'name': 'مسؤول أصلي', 'login': 'sync_orig_pm', 'email': 'sync_orig_pm@example.com',
        })
        new_pm = self.env['res.users'].create({
            'name': 'مسؤول جديد', 'login': 'sync_new_pm', 'email': 'sync_new_pm@example.com',
        })
        project = self.env['project.project'].create({
            'name': 'منصة اختبار المزامنة', 'user_id': original_pm.id,
        })
        in_progress_request = self._create_request(
            identification_id='1234567802', email='m@example.com',
            project_id=project.id, project_manager_id=original_pm.id,
        )
        # طلب ثانٍ لا يزال قيد التنفيذ على نفس المشروع - يتحقق أن المزامنة
        # تعمل صحيحاً حين تكون النتيجة أكثر من سجل واحد (message_post مثلاً
        # ينهار لو استُدعي على مجموعة سجلات بدل سجل واحد).
        second_in_progress_request = self._create_request(
            identification_id='1234567805', email='p@example.com',
            project_id=project.id, project_manager_id=original_pm.id,
        )
        done_request = self._create_request(
            identification_id='1234567803', email='n@example.com',
            project_id=project.id, project_manager_id=original_pm.id,
        )
        done_request.state = 'done'

        project.user_id = new_pm.id

        self.assertEqual(in_progress_request.project_manager_id, new_pm)
        self.assertEqual(second_in_progress_request.project_manager_id, new_pm)
        self.assertEqual(done_request.project_manager_id, original_pm)

    def test_action_reject_works_from_new_stage(self):
        """يجب أن يكون رفض الطلب متاحاً من المرحلة الأولى (قبل رفع أي
        مرفقات)، وليس فقط من مراحل الموافقة اللاحقة."""
        # action_reject تتطلب مجموعة "العمليات" - المستخدم الحالي بلا أي
        # مجموعة مخصصة افتراضياً؛ الاختبار يستهدف منطق الرفض نفسه لا الصلاحية.
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(identification_id='1234567804', email='o@example.com')
        self.assertEqual(request.stage_id.code, 'new')

        request.action_reject(reason='بيانات غير مكتملة')

        self.assertEqual(request.state, 'rejected')
        self.assertFalse(request.active)

    # ------------------------------------------------------------------
    # طلب سيارة بدون توفر سيارة حالياً: ينبّه ولا يحجب الطلب
    # ------------------------------------------------------------------
    def test_send_car_request_without_available_vehicle_still_submits(self):
        """عدم توفر سيارة حالياً يجب ألا يمنع إرسال الطلب لقسم الأسطول -
        فقط يُظهر تنبيهاً غير معطِّل، والطلب يُرفع لهم بأي حال."""
        # action_send_car_request تتطلب مجموعة "مسؤول المشروع" - الاختبار
        # يستهدف منطق التنبيه/الإرسال نفسه لا الصلاحية.
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية 11'})
        request = self._create_request(
            identification_id='1234567812', email='v@example.com', project_id=project.id,
        )

        result = request.action_send_car_request()

        self.assertTrue(request.car_requested)
        self.assertEqual(request.car_request_state, 'requested')
        self.assertEqual(result.get('tag'), 'display_notification')
        self.assertEqual(result['params']['type'], 'warning')
        # ثغرة حقيقية لاحظها المستخدم فعلياً: بدون 'next' هنا، زر "طلب
        # سيارة" يبقى ظاهراً على الشاشة رغم أن car_requested صار True فعلاً
        # - الواجهة لا تُعيد تحميل السجل تلقائياً إلا بتحديث الصفحة يدوياً
        # (F5)، لأن إرجاع أي action صريح من زر type="object" يُلغي إعادة
        # التحميل التلقائية الافتراضية (انظر الشرح الكامل في الكود). هذا
        # التسلسل ('next': act_window_close) يُعيد تفعيلها.
        self.assertEqual(
            result['params'].get('next'),
            {'type': 'ir.actions.act_window_close'},
        )

    def test_send_car_request_with_available_vehicle_no_notification(self):
        """توفر سيارة يجب ألا يُظهر أي تنبيه - إرسال طلب عادي فقط."""
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية 12'})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة تجريبية 2'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل تجريبي 2', 'brand_id': brand.id,
        })
        self.env['fleet.vehicle'].create({
            'model_id': model.id, 'recruitment_state': 'available',
        })
        request = self._create_request(
            identification_id='1234567813', email='w@example.com', project_id=project.id,
        )

        result = request.action_send_car_request()

        self.assertTrue(request.car_requested)
        self.assertEqual(request.car_request_state, 'requested')
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # ربط السيارة بفرع الطلب نفسه (بدل أي سيارة متاحة بغض النظر عن الفرع)
    # ------------------------------------------------------------------
    def _create_branch_project_request(self, identification_id, email):
        """ينشئ فرعاً (شركة تابعة) ومنصة تابعة له وطلباً عليها - مساعد
        مشترك لاختبارات ربط السيارة بالفرع أدناه."""
        branch = self.env['res.company'].create({
            'name': 'فرع تجريبي - ربط سيارة %s' % identification_id,
            'parent_id': self.env.company.id,
        })
        project = self.env['project.project'].create({
            'name': 'منصة فرع تجريبي - ربط سيارة %s' % identification_id,
            'company_id': branch.id,
        })
        request = self._create_request(
            identification_id=identification_id, email=email, project_id=project.id,
        )
        return branch, request

    def _create_test_vehicle(self, company_id=False):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة - ربط سيارة'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل - ربط سيارة', 'brand_id': brand.id,
        })
        return self.env['fleet.vehicle'].create({
            'model_id': model.id, 'company_id': company_id,
        })

    def test_vehicle_from_different_branch_rejected(self):
        """طلب صريح: لا يمكن ربط طلب توظيف بسيارة تابعة لفرع آخر عن فرع
        الطلب/الموظف نفسه."""
        branch, request = self._create_branch_project_request('1234567845', 'ao@example.com')
        other_branch = self.env['res.company'].create({
            'name': 'فرع تجريبي آخر - ربط سيارة', 'parent_id': self.env.company.id,
        })
        other_branch_vehicle = self._create_test_vehicle(company_id=other_branch.id)
        self.assertEqual(request.company_id, branch)

        with self.assertRaises(ValidationError):
            request.vehicle_id = other_branch_vehicle

    def test_vehicle_from_same_branch_allowed(self):
        branch, request = self._create_branch_project_request('1234567846', 'ap@example.com')
        same_branch_vehicle = self._create_test_vehicle(company_id=branch.id)

        request.vehicle_id = same_branch_vehicle

        self.assertEqual(request.vehicle_id, same_branch_vehicle)

    def test_vehicle_without_company_allowed_regardless_of_branch(self):
        """سيارة بلا فرع محدَّد (company_id فارغ - "متاحة لكل الفروع") لا
        يجب أن يمنعها التحقق - نفس منطق الـdomain في شاشة الأسطول."""
        branch, request = self._create_branch_project_request('1234567847', 'aq@example.com')
        shared_vehicle = self._create_test_vehicle(company_id=False)

        request.vehicle_id = shared_vehicle

        self.assertEqual(request.vehicle_id, shared_vehicle)

    # ------------------------------------------------------------------
    # جهة اتصال المرشّح الخفيفة (candidate_partner_id) - يجب ألا تتكرر
    # ------------------------------------------------------------------
    def test_get_or_create_candidate_partner_reused_across_calls(self):
        """استدعاء _get_or_create_candidate_partner() أكثر من مرة لنفس
        الطلب (من أي جهة - سيارة، رسوم حكومية...) يجب أن يعيد نفس الشريك
        دائماً، لا أن ينشئ شريكاً جديداً في كل مرة."""
        request = self._create_request(identification_id='1234567838', email='ah@example.com')

        first = request._get_or_create_candidate_partner()
        second = request._get_or_create_candidate_partner()

        self.assertEqual(first, second)
        self.assertEqual(request.candidate_partner_id, first)

    def test_create_employee_reuses_candidate_partner_as_work_contact(self):
        """جهة اتصال المرشّح المُنشأة مبكراً (مثلاً عند تسجيل رسوم حكومية)
        تُعاد استخدامها كجهة اتصال العمل الرسمية للموظف عند إنشائه، بدل
        إنشاء شريك مكرر."""
        request = self._create_request(identification_id='1234567839', email='ai@example.com')
        partner = request._get_or_create_candidate_partner()

        employee = request._create_employee()

        self.assertEqual(employee.work_contact_id, partner)

    def test_employee_name_includes_identification_id(self):
        """طلب صريح: اسم الموظف الفعلي (hr.employee.name) يتضمّن رقم
        الهوية/الإقامة ملحقاً بفاصل "|" حرفياً في كل مكان - وليس فقط في
        قوائم البحث/الاختيار."""
        request = self._create_request(
            identification_id='1234567840', email='aj@example.com',
            employee_name='أحمد أحمد زايد عواض',
        )

        employee = request._create_employee()

        self.assertEqual(employee.name, 'أحمد أحمد زايد عواض|1234567840')

    def test_employee_created_at_sponsorship_done_stage_not_started(self):
        """طلب صريح: سجل الموظف الرسمي (hr.employee) يُنشأ فور "تم نقل
        الكفالة" - وليس بانتظار "مباشرة العمل" (آخر مرحلة، بعد استلام
        السيارة) - حتى يمكن صرف سلفة له قبل استلام السيارة حتى، والسلفة
        تتطلب سجل hr.employee فعلي موجود مسبقاً."""
        request = self._create_request(identification_id='1234567841', email='ak@example.com')
        self.assertFalse(request.employee_id)

        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_sponsorship_done').id,
        })

        self.assertTrue(request.employee_id)
        # الطلب نفسه يبقى "قيد التنفيذ" - إنشاء الموظف لا يُنهي الطلب،
        # فقط "مباشرة العمل" (المرحلة الأخيرة) تفعل ذلك.
        self.assertEqual(request.state, 'in_progress')

    def test_vehicle_driver_promoted_on_authorize_when_employee_already_exists(self):
        """بعد تحويل إنشاء الموظف لمرحلة "تم نقل الكفالة" (أسبق من مرحلة
        السيارة)، ترقية "السائق المستقبلي" إلى "السائق" الفعلي يجب أن
        تحدث فور تفويض الأسطول للسيارة مباشرة - بدل انتظار مرحلة "مباشرة
        العمل" اللاحقة (لم تعد هي من تُنشئ الموظف أصلاً في هذا التسلسل)."""
        self.env.user.write({'group_ids': [
            (4, self.env.ref('recruitment_workflow.group_recruitment_workflow_fleet').id),
        ]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية - ترقية سائق'})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة - ترقية سائق'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل - ترقية سائق', 'brand_id': brand.id,
        })
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': model.id, 'recruitment_state': 'available',
        })
        request = self._create_request(
            identification_id='1234567842', email='al@example.com', project_id=project.id,
        )
        # جهة اتصال المرشّح غالباً موجودة مسبقاً واقعياً بحلول هذه المرحلة
        # (أُنشئت مبكراً عند تسجيل الرسوم الحكومية مثلاً) - فتُعاد استخدامها
        # كـwork_contact_id للموظف عند إنشائه، بدل شريك منفصل بلا صلة.
        candidate_partner = request._get_or_create_candidate_partner()
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_sponsorship_done').id,
        })
        self.assertTrue(request.employee_id)
        self.assertEqual(request.employee_id.work_contact_id, candidate_partner)
        request.write({'vehicle_id': vehicle.id, 'car_request_state': 'received'})

        request.action_fleet_authorize()

        self.assertEqual(vehicle.driver_id, request.employee_id.work_contact_id)
        self.assertFalse(vehicle.future_driver_id)

    def test_vehicle_driver_matches_employee_name_when_no_prior_candidate_partner(self):
        """ثغرة حقيقية لاحظها المستخدم فعلياً: طلب بلا أي رسوم حكومية (لا
        شيء يُنشئ جهة اتصال المرشّح مبكراً) - سجل الموظف يُنشأ عند "تم نقل
        الكفالة" بلا candidate_partner_id بعد، ثم تُفوَّض له سيارة لاحقاً.
        "السائق" الظاهر في Fleet كان ينفصل تماماً عن اسم الموظف الرسمي في
        هذه الحالة (partner مختلف كلياً لا يحمل حتى تنسيق الاسم|رقم
        الهوية) - يجب أن يتطابقا حرفياً الآن."""
        self.env.user.write({'group_ids': [
            (4, self.env.ref('recruitment_workflow.group_recruitment_workflow_fleet').id),
        ]})
        project = self.env['project.project'].create({'name': 'منصة تجريبية - سائق بلا رسوم'})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'ماركة - سائق بلا رسوم'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'موديل - سائق بلا رسوم', 'brand_id': brand.id,
        })
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': model.id, 'recruitment_state': 'available',
        })
        request = self._create_request(
            identification_id='1234567843', email='am@example.com', project_id=project.id,
            employee_name='ليلى المطيري',
        )
        # لا استدعاء لـ_get_or_create_candidate_partner هنا إطلاقاً - يحاكي
        # عدم وجود أي رسوم حكومية سجّلت جهة اتصال المرشّح مبكراً.
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.env.ref('recruitment_workflow.stage_sponsorship_done').id,
        })
        self.assertTrue(request.employee_id)
        self.assertFalse(request.candidate_partner_id)

        request.write({'vehicle_id': vehicle.id, 'car_request_state': 'received'})
        request.action_fleet_authorize()

        self.assertEqual(vehicle.driver_id, request.employee_id.work_contact_id)
        self.assertEqual(vehicle.driver_id.name, 'ليلى المطيري|1234567843')
        self.assertEqual(vehicle.driver_id.name, request.employee_id.name)

    # ------------------------------------------------------------------
    # الرسوم الحكومية (نقل الكفالة) - المبلغ الإجمالي فقط
    # ------------------------------------------------------------------
    def test_gov_fee_registered_marks_settled(self):
        # action_register_gov_fee تتطلب مجموعة "الموارد البشرية".
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(
            identification_id='1234567818', email='ab@example.com',
            gov_fee_amount=1000.0,
        )

        request.action_register_gov_fee()

        self.assertTrue(request.gov_fee_settled)

    def test_gov_fee_requires_amount_before_registering(self):
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(identification_id='1234567821', email='ae@example.com')
        with self.assertRaises(UserError):
            request.action_register_gov_fee()

    def test_gov_fee_cannot_be_settled_twice(self):
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(
            identification_id='1234567823', email='ag@example.com',
            gov_fee_amount=1000.0,
        )
        request.action_register_gov_fee()
        with self.assertRaises(UserError):
            request.action_register_gov_fee()

    def test_stage_exit_blocked_without_gov_fee_settled_when_amount_set(self):
        """لا يمكن مغادرة مرحلة "جاري نقل الكفالة" بدون تسجيل الرسوم
        الحكومية، إن حُدِّد مبلغ لها."""
        request = self._create_request(
            identification_id='1234567819', email='ac@example.com',
            gov_fee_amount=1000.0,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_sponsorship_transfer.id,
        })

        with self.assertRaises(UserError):
            request.action_next_stage()

    def test_stage_exit_allowed_without_gov_fee_settled_when_no_amount(self):
        """لا قيد إطلاقاً لو لم يُحدَّد أي مبلغ للرسوم الحكومية أصلاً."""
        # مغادرة مرحلة "جاري نقل الكفالة" تتطلب مجموعة "الموارد البشرية"
        # (_STAGE_APPROVAL_GROUP) - الاختبار يستهدف شرط المبلغ نفسه لا الصلاحية.
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(
            identification_id='1234567820', email='ad@example.com',
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_sponsorship_transfer.id,
        })

        request.action_next_stage()

        self.assertEqual(request.stage_id.code, 'sponsorship_done')

    def test_gov_fee_unlocked_after_return_to_stage(self):
        """"إرجاع للتصحيح" يفتح قفل مبلغ الرسوم الحكومية مجدداً - وإلا
        يبقى الحقل مقفولاً للأبد رغم الرجوع لمرحلة سابقة (كان هذا خطأً
        سابقاً: action_return_to_stage لا يمسّ gov_fee_settled إطلاقاً،
        فيبقى readonly="gov_fee_settled" في العرض ساري المفعول للأبد)."""
        self.env.user.write({'group_ids': [(4, self.group_manager.id)]})
        request = self._create_request(
            identification_id='1234567824', email='ah@example.com',
            gov_fee_amount=1000.0,
        )
        request.with_context(skip_stage_validation=True).write({
            'stage_id': self.stage_sponsorship_transfer.id,
        })
        request.action_register_gov_fee()
        self.assertTrue(request.gov_fee_settled)

        request.action_return_to_stage(self.stage_project_review, 'مبلغ خاطئ')

        self.assertFalse(request.gov_fee_settled)
        request.gov_fee_amount = 1500.0
        self.assertEqual(request.gov_fee_amount, 1500.0)
