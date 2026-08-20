# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSettlementMixin(TransactionCase):
    """يتحقق من قفل الحقول المالية بعد إنشاء القيد المحاسبي، ومن اشتقاق
    الشركة من فرع الموظف المختار تلقائياً."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # TransactionCase يُشغِّل الاختبارات افتراضياً باسم superuser
        # (uid=1، __system__) - وهو ليس عضواً تلقائياً في أي من مجموعات
        # السداد البنكي المخصَّصة (فقط base.user_admin مُضاف صراحة لمجموعة
        # المدير العام عبر security.xml، والتي تتضمّن المحاسب/المستخدم
        # تلقائياً عبر implied_ids) - فنستبدل مستخدم البيئة الافتراضي هنا
        # مرة واحدة بدل إضافة with_user() لكل استدعاء عبر كل الاختبارات.
        cls.env = cls.env(user=cls.env.ref('base.user_admin'))
        cls.GovFee = cls.env['bank.settlement.government.fee']
        cls.Representative = cls.env['bank.settlement.representative']
        cls.Advance = cls.env['bank.settlement.advance']

    def _create_gov_fee(self):
        return self.GovFee.create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': 500.0,
        })

    def _complete_to_confirmed(self, rec):
        # دفتر اليومية/الحساب المرتبط لا يُسمح بتحديدهما إلا بعد الاعتماد
        # تحديداً (حالة "مؤكدة") - فيُضبطان بعد action_confirm() وليس
        # قبله (انظر test_bank_fields_only_editable_after_gm_approval).
        rec.action_submit_review()
        rec.action_confirm()
        rec.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', rec.company_id.id)], limit=1).id,
        })

    def _complete_to_done(self, rec):
        self._complete_to_confirmed(rec)
        rec.action_done()

    def test_amount_locked_after_approval_even_before_move_created(self):
        """القفل يبدأ فور اعتماد المدير العام (تأكيد) - وليس فقط بعد
        إنشاء القيد المحاسبي فعلياً، حتى لا يُعتمَد على مبلغ ثم يُغيَّر
        قبل السداد الفعلي."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        self.assertFalse(gov_fee.move_id)

        with self.assertRaises(UserError):
            gov_fee.write({'amount': 999.0})

    def test_fields_locked_immediately_after_submit_review(self):
        """القفل يبدأ فور "إرسال للمراجعة" مباشرة - قبل تأكيد المدير
        العام بخطوة كاملة - في كل شاشات السداد البنكي (وليس السلفة
        فقط)، بناءً على طلب صريح لتعميم نفس قاعدة السلفة."""
        other_employee = self.env['hr.employee'].create({'name': 'موظف آخر - قفل مبكر'})
        gov_fee = self._create_gov_fee()
        gov_fee.action_submit_review()
        self.assertEqual(gov_fee.state, 'under_review')

        with self.assertRaises(UserError):
            gov_fee.write({'amount': 999.0})
        with self.assertRaises(UserError):
            gov_fee.write({'employee_id': other_employee.id})

    def test_bank_fields_only_editable_after_gm_approval(self):
        """دفتر اليومية والحساب المرتبط: يُمنع تحديدهما قبل اعتماد المدير
        العام (لا يظهران أصلاً في الواجهة قبل ذلك)، يُسمح بتحديدهما في
        حالة "مؤكدة" تحديداً، ثم يُقفلان مجدداً بعد "منفّذة" (تم إنشاء
        القيد المحاسبي فعلاً بقيمتيهما، فلا معنى لتغييرهما بعدها)."""
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        account = self.env['account.account'].search([], limit=1)
        gov_fee = self._create_gov_fee()

        with self.assertRaises(UserError):
            gov_fee.write({'journal_id': journal.id})

        gov_fee.action_submit_review()
        with self.assertRaises(UserError):
            gov_fee.write({'linked_account_id': account.id})

        gov_fee.action_confirm()
        self.assertEqual(gov_fee.state, 'confirmed')
        gov_fee.write({'journal_id': journal.id, 'linked_account_id': account.id})
        self.assertEqual(gov_fee.journal_id, journal)
        self.assertEqual(gov_fee.linked_account_id, account)

        gov_fee.action_done()
        with self.assertRaises(UserError):
            gov_fee.write({'linked_account_id': self.env['account.account'].search(
                [('id', '!=', account.id)], limit=1).id})

    def test_employee_locked_after_approval(self):
        """الموظف (الشخص) يُقفل هو أيضاً بعد الاعتماد - وليس فقط المبلغ."""
        other_employee = self.env['hr.employee'].create({'name': 'موظف آخر'})
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        with self.assertRaises(UserError):
            gov_fee.write({'employee_id': other_employee.id})

    def test_project_locked_after_approval(self):
        """المنصة (project_id) تُقفل هي أيضاً بعد الاعتماد - تُشتق من
        الموظف المختار (وحساب المنصة التحليلي يُحسب منها)، فلا يجوز
        تغييرها يدوياً بعد الاعتماد رغم بقاء الموظف نفسه مقفولاً هو
        الآخر - وإلا أمكن تغيير العزل المالي بين المنصات لسجل معتمَد
        فعلاً."""
        other_project = self.env['project.project'].create({'name': 'منصة أخرى'})
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        with self.assertRaises(UserError):
            gov_fee.write({'project_id': other_project.id})

    def test_type_fields_locked_after_approval(self):
        """نوع الرسوم/الجهة الحكومية يُقفلان هما أيضاً بعد الاعتماد."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        with self.assertRaises(UserError):
            gov_fee.write({
                'fee_type_id': self.env.ref('bank_settlement.government_fee_type_office_fee').id,
            })

    def test_settlement_move_flagged_for_restricted_visibility(self):
        """القيد الناتج عن السداد البنكي يُعلَّم بـ is_bank_settlement_move
        - يُستخدم لحصر رؤية "مستخدم/محاسب" السداد البنكي عليه فقط، دون
        كشف بقية قيود المحاسبة (انظر ir.rule في security.xml)."""
        gov_fee = self._create_gov_fee()
        self._complete_to_done(gov_fee)

        self.assertTrue(gov_fee.move_id.is_bank_settlement_move)

    def test_amount_editable_before_approval(self):
        gov_fee = self._create_gov_fee()
        gov_fee.write({'amount': 750.0})
        self.assertEqual(gov_fee.amount, 750.0)

    def test_reset_draft_reopens_editing(self):
        """بعد "إعادة لمسودة" (مدير عام فقط، ولا قيد محاسبي بعد) يعود
        التعديل ممكناً مجدداً."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        gov_fee.action_reset_draft(reason='بيانات خاطئة')

        gov_fee.write({'amount': 999.0})
        self.assertEqual(gov_fee.amount, 999.0)

    def test_approval_lock_bypassed_with_explicit_context_flag(self):
        """آلية الاستكمال التلقائي لحقل الموظف (candidate → hr.employee
        رسمي) يجب أن تتجاوز القفل عمداً عبر السياق الصريح."""
        other_employee = self.env['hr.employee'].create({'name': 'موظف استكمال'})
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        gov_fee.with_context(bank_settlement_skip_approval_lock=True).write({
            'employee_id': other_employee.id,
        })
        self.assertEqual(gov_fee.employee_id, other_employee)

    def test_representative_settlement_amount_locked_after_approval(self):
        """settlement_amount هو الاسم البديل لـ amount في هذا النموذج -
        يجب أن يُقفل هو أيضاً، وليس فقط amount مباشرة."""
        rep = self.Representative.create({'settlement_amount': 400.0})
        self._complete_to_confirmed(rep)

        with self.assertRaises(UserError):
            rep.write({'settlement_amount': 999.0})

    def test_company_derived_from_employee_branch(self):
        """اختيار موظف تابع لفرع معيّن يُحدّث شركة السجل تلقائياً لتطابق
        فرعه - بدل بقائها على الشركة الافتراضية للجلسة."""
        branch = self.env['res.company'].create({
            'name': 'فرع تجريبي - سداد بنكي', 'parent_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'موظف فرع تجريبي', 'company_id': branch.id,
        })
        gov_fee = self._create_gov_fee()
        self.assertNotEqual(gov_fee.company_id, branch)

        gov_fee.employee_id = employee
        gov_fee._onchange_employee_id()

        self.assertEqual(gov_fee.company_id, branch)

    def test_advance_locked_immediately_after_submit_review(self):
        """السلفة تحديداً: حالاتها القابلة للتعديل هي "مسودة" فقط - أي
        القفل يبدأ فور "إرسال للمراجعة" مباشرة، قبل أي موافقة من مسؤول
        المشروع أو المدير العام (أشد من النموذج الأساسي الذي يسمح
        بالتعديل حتى مرحلة المراجعة)."""
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
        })
        advance.action_submit_review()
        self.assertEqual(advance.state, 'waiting_approval')

        with self.assertRaises(UserError):
            advance.write({'amount': 999.0})
        with self.assertRaises(UserError):
            advance.write({'employee_id': self.env['hr.employee'].create(
                {'name': 'موظف سلفة آخر'}).id})

    def test_advance_bank_fields_only_editable_after_gm_approval(self):
        """دفتر اليومية والحساب المرتبط في السلفة تحديداً: يُمنع تحديدهما
        قبل اعتماد المدير العام (حتى لو كان السجل لا يزال "مسودة")، ويجب
        أن يكون تحديدهما ممكناً في حالة "تمت الموافقة" تحديداً - لا يجوز
        أن يبقيا مقفولين لمجرّد أن السجل غادر "مسودة" (كان هذا خطأً سابقاً:
        القفل العام لبقية حقول السلفة كان يشمل هذين الحقلين أيضاً رغم أنهما
        لا يظهران أصلاً إلا بعد الاعتماد)."""
        journal = self.env['account.journal'].search([], limit=1)
        account = self.env['account.account'].search([], limit=1)
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
        })

        with self.assertRaises(UserError):
            advance.write({'journal_id': journal.id})

        advance.action_submit_review()
        advance.action_pm_approve()
        with self.assertRaises(UserError):
            advance.write({'linked_account_id': account.id})

        advance.action_confirm()
        self.assertEqual(advance.state, 'approved')
        advance.write({'journal_id': journal.id, 'linked_account_id': account.id})
        self.assertEqual(advance.journal_id, journal)
        self.assertEqual(advance.linked_account_id, account)

    def test_draft_record_can_be_deleted_but_submitted_cannot(self):
        """سجل السداد البنكي سجل تدقيق دائم بعد مغادرة "مسودة" - لا يجوز
        حذفه نهائياً حتى لمن يملك صلاحية الحذف (مدير عام السداد البنكي)،
        للحفاظ على أثر كامل لكل سجل رُفع للمراجعة أو اعتُمد أو نُفِّذ."""
        draft_fee = self._create_gov_fee()
        draft_fee.unlink()
        self.assertFalse(draft_fee.exists())

        submitted_fee = self._create_gov_fee()
        submitted_fee.action_submit_review()

        with self.assertRaises(UserError):
            submitted_fee.unlink()
        self.assertTrue(submitted_fee.exists())

    def test_transfer_date_and_bank_reference_only_editable_after_gm_approval(self):
        """تاريخ التحويل ورقم السداد البنكي - بيانات السداد الفعلي، خاصة
        بالمحاسب وقت الصرف تحديداً - يُمنع تحديدهما قبل اعتماد المدير
        العام (لا يظهران أصلاً في الواجهة قبل ذلك، بنفس منطق دفتر
        اليومية/الحساب المرتبط)، يُسمح بتحديدهما في حالة "مؤكدة" تحديداً
        (طلب صريح)، ثم يُقفلان مجدداً بعد "منفّذة"."""
        gov_fee = self._create_gov_fee()

        with self.assertRaises(UserError):
            gov_fee.write({'transfer_date': '2025-01-01'})

        gov_fee.action_submit_review()
        with self.assertRaises(UserError):
            gov_fee.write({'bank_reference': 'REF-123'})

        gov_fee.action_confirm()
        self.assertEqual(gov_fee.state, 'confirmed')
        gov_fee.write({'transfer_date': '2025-01-01', 'bank_reference': 'REF-123'})
        self.assertEqual(str(gov_fee.transfer_date), '2025-01-01')
        self.assertEqual(gov_fee.bank_reference, 'REF-123')

        gov_fee.write({
            'linked_account_id': self.env['account.account'].search([], limit=1).id,
            'journal_id': self.env['account.journal'].search(
                [('company_id', '=', gov_fee.company_id.id)], limit=1).id,
        })
        gov_fee.action_done()
        with self.assertRaises(UserError):
            gov_fee.write({'bank_reference': 'REF-456'})

    def test_negative_amount_rejected(self):
        with self.assertRaises(UserError):
            self._create_gov_fee().write({'amount': -100.0})
        with self.assertRaises(UserError):
            self.GovFee.create({
                'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
                'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
                'amount': -100.0,
            })

    def test_zero_amount_blocks_submit_review(self):
        """لا يجوز إرسال سجل بمبلغ صفري/فارغ للمراجعة - وإلا أمكن مروره
        حتى "منفّذة" وإنشاء قيد محاسبي فعلي بمبلغ غير منطقي (ثغرة حقيقية
        مكتشفة بمراجعة شاملة: لم يكن يوجد أي تحقق سابقاً)."""
        gov_fee = self.GovFee.create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
        })
        with self.assertRaises(UserError):
            gov_fee.action_submit_review()

    def test_company_isolation_between_branches(self):
        """مستخدم شركة/فرع لا يجب أن يرى سجلات سداد بنكي تخص فرعاً آخر -
        كانت هذه ثغرة موثّقة صراحة في الكود (لا Record Rules على نماذج
        السداد البنكي نفسها)."""
        branch_a = self.env['res.company'].create({
            'name': 'فرع أ - عزل سداد بنكي', 'parent_id': self.env.company.id,
        })
        branch_b = self.env['res.company'].create({
            'name': 'فرع ب - عزل سداد بنكي', 'parent_id': self.env.company.id,
        })
        fee_a = self._create_gov_fee()
        fee_a.company_id = branch_a.id
        fee_b = self._create_gov_fee()
        fee_b.company_id = branch_b.id

        user_group = self.env.ref('bank_settlement.group_bank_settlement_user')
        branch_a_user = self.env['res.users'].create({
            'name': 'مستخدم فرع أ - سداد بنكي',
            'login': 'branch_a_bank_settlement_user',
            'email': 'branch_a_bank_settlement_user@example.com',
            'company_ids': [(6, 0, [branch_a.id])],
            'company_id': branch_a.id,
            'group_ids': [(6, 0, [user_group.id, self.env.ref('base.group_user').id])],
        })

        visible = self.GovFee.with_user(branch_a_user).search([
            ('id', 'in', (fee_a | fee_b).ids),
        ])
        self.assertEqual(visible, fee_a)

    def test_company_derived_server_side_on_create_without_onchange(self):
        """يجب أن يعمل الاشتقاق من جهة الخادم مباشرة (create()/write())
        بدون الاعتماد على onchange إطلاقاً - يغطي: (1) الحقل غير معروض
        في بعض الشاشات فيُهمَل تحديثه المرئي عند الحفظ، (2) أي إنشاء عبر
        RPC/API مباشر لا يمر بـ onchange أصلاً."""
        branch = self.env['res.company'].create({
            'name': 'فرع تجريبي - سداد بنكي 2', 'parent_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'موظف فرع تجريبي 2', 'company_id': branch.id,
        })

        gov_fee = self.GovFee.create({
            'government_entity_id': self.env.ref('bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref('bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': 500.0,
            'employee_id': employee.id,
        })

        self.assertEqual(gov_fee.company_id, branch)

    def test_insurance_transfer_creation_is_idempotent(self):
        """استدعاء action_create_insurance_transfer مرتين (نقرة مزدوجة/
        RPC مكرر) يجب ألا ينشئ فاتورة مورد ثانية - كان بلا أي تحقق
        سابقاً (بعكس action_done المشتركة)، فيُنشئ فاتورتين حقيقيتين
        لنفس السجل."""
        vendor = self.env['res.partner'].create({'name': 'مورد تأمين تجريبي'})
        insurance = self.env['bank.settlement.medical.insurance'].create({
            'fee_type_id': self.env.ref('bank_settlement.medical_insurance_type_medical_insurance').id,
            'vendor_id': vendor.id,
            'amount': 300.0,
        })
        insurance.action_submit_review()
        insurance.action_confirm()

        first_move = insurance.action_create_insurance_transfer()
        second_move = insurance.action_create_insurance_transfer()

        self.assertEqual(first_move, second_move)
        self.assertEqual(insurance.state, 'done')

    def test_config_list_rejects_duplicate_name(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger

        self.env['bank.settlement.advance.reason'].create({'name': 'سبب تجريبي فريد'})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['bank.settlement.advance.reason'].create({'name': 'سبب تجريبي فريد'})

    def test_advance_iban_and_stc_number_changes_are_tracked(self):
        """آيبان الموظف ورقم STC Pay (وجهة صرف السلفة الفعلية) كانا بلا
        أي تتبع (tracking) إطلاقاً - أي تعديل عليهما لم يكن يظهر في سجل
        المتابعة (من عدّله ومتى والقيمة القديمة)، ثغرة تدقيق حقيقية على
        حقول تمثّل بالضبط أين تذهب الأموال (ثغرة مكتشفة بمراجعة شاملة)."""
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
            'payment_method': 'bank_transfer',
            'employee_iban': 'SA0000000000000000000001',
        })
        # رسالة التتبع (tracking) تُسجَّل فعلياً عبر precommit hook (انظر
        # mail_thread._message_track: self.env.cr.precommit.data) - لا
        # تُنشأ مباشرة ضمن write()/create() نفسها. يجب تفريغها هنا (بعد
        # الإنشاء تحديداً، قبل قراءة العدّاد "قبل") وإلا يتراكم تسجيل
        # تتبّع الإنشاء مع تسجيل تتبّع التعديل التالي معاً في نفس التفريغ
        # فيضيع أحدهما (ثغرة تجريبية مكتشفة بالتجربة الفعلية - في
        # الاستخدام الفعلي هذا يحدث تلقائياً وبشكل منفصل قبل انتهاء أي
        # طلب HTTP/RPC عادي، فلا يظهر هناك).
        self.env.cr.flush()
        message_count_before = len(advance.message_ids)

        advance.employee_iban = 'SA0000000000000000000002'
        self.env.cr.flush()

        self.assertGreater(len(advance.message_ids), message_count_before)

    def test_representative_iban_change_is_tracked(self):
        rep = self.Representative.create({'settlement_amount': 400.0, 'iban': 'SA1111111111111111111111'})
        # انظر الشرح الكامل في test_advance_iban_and_stc_number_changes_are_tracked
        self.env.cr.flush()
        message_count_before = len(rep.message_ids)

        rep.iban = 'SA2222222222222222222222'
        self.env.cr.flush()

        self.assertGreater(len(rep.message_ids), message_count_before)

    def test_activity_scheduled_for_manager_on_submit_review(self):
        """كان السداد البنكي بلا أي إشعار فعلي إطلاقاً - يجب أن يصل تنبيه
        (Activity) تلقائي لمدير عام السداد البنكي فور "إرسال للمراجعة"،
        بدل تفقّد القوائم يدوياً."""
        gov_fee = self._create_gov_fee()

        gov_fee.action_submit_review()

        self.assertTrue(gov_fee.activity_ids)
        notified_user = gov_fee.activity_ids[:1].user_id
        self.assertTrue(
            notified_user.has_group('bank_settlement.group_bank_settlement_manager'),
            'المستخدَم المُخطَر يجب أن يكون عضواً في مجموعة مدير عام السداد البنكي.',
        )
        # رسالة مباشرة في صندوق الدردشة (Discuss/الجرس) بالإضافة للنشاط -
        # طلب صريح، الأنشطة وحدها لا تظهر هناك.
        self.assertIn(notified_user.partner_id, gov_fee.message_ids[:1].partner_ids)

    def test_activity_scheduled_for_accountant_on_confirm(self):
        """بعد اعتماد المدير العام، يجب أن يصل تنبيه للمحاسب (وليس مدير
        عام آخر) - هو المسؤول عن تنفيذ الصرف التالي."""
        gov_fee = self._create_gov_fee()
        gov_fee.action_submit_review()

        gov_fee.action_confirm()

        self.assertTrue(gov_fee.activity_ids)
        notified_user = gov_fee.activity_ids[:1].user_id
        self.assertTrue(
            notified_user.has_group('bank_settlement.group_bank_settlement_reviewer'),
            'المستخدَم المُخطَر يجب أن يكون عضواً في مجموعة المحاسب.',
        )

    def test_previous_activity_closed_on_state_change(self):
        """النشاط السابق (المرتبط بحالة سابقة) يجب أن يُغلَق تلقائياً عند
        تغيّر الحالة - وإلا تراكمت تنبيهات قديمة لم تعد ذات معنى.

        ملاحظة: action_feedback() في هذا الإصدار من Odoo يُؤرشِف النشاط
        المكتمل (active=False) بدل حذفه نهائياً - يبقى موجوداً كسجل
        تاريخي (مع رسالة "تم" في الدردشة)، فلا يظهر ضمن activity_ids
        (التي تُصفّي على active=True ضمنياً مثل أي حقل عادي)."""
        gov_fee = self._create_gov_fee()
        gov_fee.action_submit_review()
        first_activity = gov_fee.activity_ids

        gov_fee.action_confirm()

        self.assertFalse(first_activity.active)
        self.assertNotIn(first_activity, gov_fee.activity_ids)

    def test_advance_activity_scheduled_for_specific_project_manager(self):
        """السلفة تحديداً: الإشعار عند "إرسال للمراجعة" يستهدف مسؤول
        مشروع الموظف نفسه تحديداً (وليس أول عضو عشوائي بمجموعة مسؤولي
        المشاريع) - بنفس منطق التحقق الفعلي في action_pm_approve."""
        pm_group = self.env.ref('recruitment_workflow.group_recruitment_workflow_project_manager')
        assigned_pm = self.env['res.users'].create({
            'name': 'مسؤول مشروع معيّن - إشعار سلفة',
            'login': 'advance_notify_assigned_pm',
            'email': 'advance_notify_assigned_pm@example.com',
            'group_ids': [(6, 0, [pm_group.id, self.env.ref('base.group_user').id])],
        })
        project = self.env['project.project'].create({
            'name': 'مشروع تجريبي - إشعار سلفة', 'user_id': assigned_pm.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'موظف سلفة - إشعار', 'project_id': project.id,
        })
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref('bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0, 'employee_id': employee.id,
        })

        advance.action_submit_review()

        self.assertTrue(advance.activity_ids)
        self.assertEqual(advance.activity_ids[:1].user_id, assigned_pm)

    def test_return_to_previous_stage_preserves_state_and_logs_reason(self):
        """"إرجاع للتصحيح" يُرجع السجل خطوة واحدة فقط (مؤكدة -> تحت
        المراجعة) - بعكس "إعادة لمسودة" التي تمسح كل شيء دفعة واحدة -
        ويُسجّل السبب في سجل المتابعة."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        message_count_before = len(gov_fee.message_ids)

        gov_fee.action_return_to_previous_stage(reason='اعتماد المدير العام كان خطأً')

        self.assertEqual(gov_fee.state, 'under_review')
        self.assertGreater(len(gov_fee.message_ids), message_count_before)

    def test_return_to_previous_stage_blocked_without_previous_stage(self):
        """لا توجد مرحلة سابقة ذات معنى من "تحت المراجعة" (البديل هو
        "إعادة لمسودة" نفسها) - يجب رفض المحاولة، سواء عبر الإجراء
        مباشرة أو عبر فتح المعالج."""
        gov_fee = self._create_gov_fee()
        gov_fee.action_submit_review()
        self.assertEqual(gov_fee.state, 'under_review')

        with self.assertRaises(UserError):
            gov_fee.action_return_to_previous_stage(reason='سبب ما')
        with self.assertRaises(UserError):
            gov_fee.action_open_return_wizard()

    def test_return_to_previous_stage_requires_reason(self):
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        with self.assertRaises(UserError):
            gov_fee.action_return_to_previous_stage(reason=False)
        self.assertEqual(gov_fee.state, 'confirmed')

    def test_return_to_previous_stage_requires_manager_group(self):
        """محاسب (مجموعة "reviewer") لا يملك صلاحية "إرجاع للتصحيح" -
        نفس صلاحية "إعادة لمسودة" تحديداً (مدير عام السداد البنكي)،
        وليست متاحة لمن يستطيع فقط تنفيذ الصرف."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        reviewer_group = self.env.ref('bank_settlement.group_bank_settlement_reviewer')
        reviewer_user = self.env['res.users'].create({
            'name': 'محاسب - اختبار إرجاع للتصحيح',
            'login': 'return_wizard_reviewer_only',
            'email': 'return_wizard_reviewer_only@example.com',
            'group_ids': [(6, 0, [reviewer_group.id, self.env.ref('base.group_user').id])],
        })

        with self.assertRaises(UserError):
            gov_fee.with_user(reviewer_user).action_return_to_previous_stage(reason='محاولة غير مصرَّح بها')
        self.assertEqual(gov_fee.state, 'confirmed')

    def test_return_wizard_delegates_to_action(self):
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        wizard = self.env['bank.settlement.return.wizard'].with_context(
            default_res_model=gov_fee._name, default_res_id=gov_fee.id,
        ).create({
            'res_model': gov_fee._name, 'res_id': gov_fee.id,
            'target_state': 'under_review',
            'reason': 'سبب عبر المعالج',
        })

        wizard.action_confirm_return()

        self.assertEqual(gov_fee.state, 'under_review')

    def test_return_wizard_target_state_selection_matches_record(self):
        """قائمة "الإرجاع إلى مرحلة" في المعالج تُبنى ديناميكياً من
        _get_returnable_stages() الخاصة بالسجل المستهدف نفسه - وليست
        قائمة ثابتة لكل النماذج."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)
        wizard = self.env['bank.settlement.return.wizard'].with_context(
            default_res_model=gov_fee._name, default_res_id=gov_fee.id,
        ).new({'res_model': gov_fee._name, 'res_id': gov_fee.id})

        self.assertEqual(
            wizard._selection_target_state(),
            [('under_review', 'تحت المراجعة')],
        )

    def test_advance_return_wizard_allows_choosing_further_stage_directly(self):
        """السلفة تحديداً: من "تمت الموافقة"، يمكن اختيار "بانتظار
        الموافقة" مباشرة عبر المعالج (تخطي "وافق مسؤول المشروع")، بدل
        إلزامية التراجع خطوة واحدة فقط في كل مرة."""
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        advance.action_confirm()
        self.assertEqual(advance.state, 'approved')

        wizard = self.env['bank.settlement.return.wizard'].with_context(
            default_res_model=advance._name, default_res_id=advance.id,
        ).create({
            'res_model': advance._name, 'res_id': advance.id,
            'target_state': 'waiting_approval',
            'reason': 'كلا الموافقتين كانتا خاطئتين',
        })

        wizard.action_confirm_return()

        self.assertEqual(advance.state, 'waiting_approval')

    def test_return_to_previous_stage_rejects_invalid_target_state(self):
        """محاولة تمرير target_state لا يعيده _get_returnable_stages
        للسجل يجب أن تُرفض - طبقة حماية إضافية من جهة الخادم، دفاعاً ضد
        استدعاء RPC مباشر يتجاوز قائمة المعالج."""
        gov_fee = self._create_gov_fee()
        self._complete_to_confirmed(gov_fee)

        with self.assertRaises(UserError):
            gov_fee.action_return_to_previous_stage(
                target_state='draft', reason='محاولة قفز غير صالحة',
            )
        self.assertEqual(gov_fee.state, 'confirmed')

    def test_return_wizard_rejects_invalid_res_model(self):
        wizard = self.env['bank.settlement.return.wizard'].create({
            'res_model': 'res.partner', 'res_id': self.env.user.partner_id.id,
            'target_state': 'under_review', 'reason': 'محاولة نموذج غير صالح',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_return()

    def test_advance_return_to_previous_stage_preserves_earlier_approval(self):
        """السلفة: التراجع من "تمت الموافقة" (اعتماد المدير العام) يعيدها
        إلى "وافق مسؤول المشروع" - أي يُلغي اعتماد المدير العام فقط،
        ويُبقي موافقة مسؤول المشروع سارية (بعكس "إعادة لمسودة" التي كانت
        ستمسح الاثنتين معاً)."""
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        advance.action_confirm()
        self.assertEqual(advance.state, 'approved')

        advance.action_return_to_previous_stage(reason='اعتماد المدير العام كان خطأً')

        self.assertEqual(advance.state, 'pm_approved')

        # المرحلة السابقة (pm_approved) نفسها تُمثّل موافقة مسؤول المشروع
        # قائمة - إعادة تنفيذ اعتماد المدير العام وحده كافٍ لإكمال السلسلة
        # دون إعادة طلب موافقة مسؤول المشروع من جديد.
        advance.action_confirm()
        self.assertEqual(advance.state, 'approved')

    def test_advance_return_to_previous_stage_second_step(self):
        """التراجع من "وافق مسؤول المشروع" يعيد السلفة إلى "بانتظار
        الموافقة" - الخطوة الثانية ذات المعنى في سلسلة السلفة."""
        advance = self.Advance.create({
            'advance_reason_id': self.env.ref(
                'bank_settlement.advance_reason_salary_advance').id,
            'amount': 300.0,
        })
        advance.action_submit_review()
        advance.action_pm_approve()
        self.assertEqual(advance.state, 'pm_approved')

        advance.action_return_to_previous_stage(reason='موافقة مسؤول المشروع كانت خطأً')

        self.assertEqual(advance.state, 'waiting_approval')

    def test_return_to_previous_stage_blocked_when_move_exists(self):
        """لا يمكن الإرجاع للتصحيح بعد إنشاء القيد المحاسبي فعلياً (حالة
        "منفّذة") - لا توجد مرحلة سابقة معرَّفة من هذه الحالة أصلاً."""
        gov_fee = self._create_gov_fee()
        self._complete_to_done(gov_fee)
        self.assertEqual(gov_fee.state, 'done')

        with self.assertRaises(UserError):
            gov_fee.action_return_to_previous_stage(reason='سبب ما')
