# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class RecruitmentRequest(models.Model):
    """يربط طلب التوظيف تلقائياً بسجل "الرسوم الحكومية" في السداد البنكي
    فور تسجيل المبلغ الإجمالي لرسوم نقل الكفالة - بدل بقاء هذا السجل
    منفصلاً بلا علاقة بطلب التوظيف، أو الاضطرار لإنشائه يدوياً لاحقاً.

    هذا الملف موجود في bank_settlement وليس recruitment_workflow عمداً:
    bank_settlement يعتمد على recruitment_workflow (وليس العكس)، فهو
    الجهة الوحيدة القادرة تقنياً على التوسّع على نموذج recruitment.request.
    """
    _inherit = 'recruitment.request'

    bank_settlement_gov_fee_id = fields.Many2one(
        'bank.settlement.government.fee', string='سجل الرسوم الحكومية',
        readonly=True, copy=False,
    )
    bank_settlement_gov_fee_state = fields.Selection(
        related='bank_settlement_gov_fee_id.state', string='حالة سداد الرسوم الحكومية',
        readonly=True,
    )
    import_request_id = fields.Many2one(
        'recruitment.import.request', string='طلب الاستقدام الأصلي',
        readonly=True, copy=False,
        help='إن أُنشئ هذا الطلب تلقائياً من "طلب استقدام" (is_import_request) '
             '- يشير هنا لسجله الأصلي هناك (الرسوم/الموظف أُنشئا منه).',
    )

    def action_register_gov_fee(self):
        result = super().action_register_gov_fee()
        for rec in self:
            if not rec.bank_settlement_gov_fee_id:
                rec.bank_settlement_gov_fee_id = rec._create_bank_settlement_gov_fee_record()
        return result

    def _unlock_gov_fee_for_correction(self):
        """يُستدعى من "إرجاع للتصحيح" (action_return_to_stage) - يعالج
        سجل "الرسوم الحكومية" المرتبط بالسداد البنكي (إن وُجد) قبل فتح
        قفل المبلغ على طلب التوظيف نفسه:
        - سُدِّدت فعلاً (state == 'done') => يُمنَع الإرجاع كلياً؛ القيد
          المحاسبي الفعلي موجود، والتصحيح يجب أن يمر من السداد البنكي
          نفسه (عكس/إلغاء القيد) وليس من هنا.
        - لم تُسدَّد بعد (مسودة/تحت المراجعة/مؤكدة) => move_id فارغ حتماً
          في هذه الحالات (لا يُنشأ إلا داخل action_done نفسها)، فيُحذف
          السجل بأمان بلا أي قيد محاسبي معلَّق، ليُنشأ سجل جديد بالمبلغ
          المصحَّح تلقائياً عند إعادة الضغط على "تسجيل الرسوم الحكومية"."""
        self.ensure_one()
        gov_fee = self.bank_settlement_gov_fee_id
        if gov_fee:
            if gov_fee.state == 'done':
                raise UserError(
                    'لا يمكن "إرجاع للتصحيح" - الرسوم الحكومية سُدِّدت '
                    'فعلاً من السداد البنكي (%s). راجع/اعكس القيد '
                    'المحاسبي من هناك أولاً إن احتجت تصحيح المبلغ.'
                    % gov_fee.name
                )
            self.bank_settlement_gov_fee_id = False
            # يتجاوز قفل "لا حذف بعد مغادرة مسودة" عمداً - هذا حذف نظامي
            # لسجل غير مسدَّد بعد (تحقّقنا للتو من ذلك أعلاه)، وليس حذفاً
            # يدوياً حقيقياً من مستخدم يتجاوز سجل التدقيق (انظر bank_
            # settlement_mixin.unlink()).
            gov_fee.sudo().with_context(
                bank_settlement_skip_approval_lock=True,
            ).unlink()
        return super()._unlock_gov_fee_for_correction()

    def _validate_stage_exit(self, current_stage):
        """يضيف شرط مرحلة "تم السداد" الفعلي عندكم: تأكيد سداد إجمالي
        الرسوم الحكومية للمنصة/الجهة الحكومية (سجل "الرسوم الحكومية" في
        السداد البنكي بحالة "منفّذة") - بدل شرط فاتورة المورّد الخارجي
        غير المستخدم أصلاً (recruitment_workflow الأساسي يتجاوزه الآن إن
        كان fee_amount صفراً)."""
        super()._validate_stage_exit(current_stage)
        self.ensure_one()
        if current_stage.code == 'paid' and self.gov_fee_amount > 0:
            if not self.bank_settlement_gov_fee_id:
                raise UserError(
                    'لا يمكن الانتقال للمرحلة التالية. يجب تسجيل الرسوم '
                    'الحكومية أولاً (زر "تسجيل الرسوم الحكومية").'
                )
            if self.bank_settlement_gov_fee_id.state != 'done':
                raise UserError(
                    'لا يمكن الانتقال للمرحلة التالية. لم يُؤكَّد سداد '
                    'الرسوم الحكومية للمنصة/الجهة الحكومية بعد من السداد '
                    'البنكي (%s) - يجب إتمامه من هناك أولاً.'
                    % self.bank_settlement_gov_fee_id.name
                )

    def _create_bank_settlement_gov_fee_record(self):
        """ينشئ سجل "رسوم حكومية" في السداد البنكي فوراً، معبَّأً بنفس
        المبلغ الإجمالي المسجَّل على طلب التوظيف - بدون موظف رسمي بعد (لا
        سجل hr.employee وقت نقل الكفالة)، لكن مرتبطاً فوراً بجهة اتصال
        المرشّح الخفيفة (candidate_partner_id) كشريك على القيد المحاسبي -
        بدل بقاء القيد بلا شريك حتى إنشاء سجل الموظف الرسمي المتأخر لآخر
        مرحلة. يُكمَل حقل الموظف نفسه لاحقاً تلقائياً في _create_employee()
        أدناه.

        ملاحظة: "الجهة الحكومية" تُضبط افتراضياً بـ"وزارة الداخلية (مقيم)"
        - عدّلها يدوياً من سجل الرسوم نفسه في السداد البنكي إن كانت جهة
        نقل الكفالة الفعلية مختلفة (مثال: قوى/مساند).
        """
        self.ensure_one()
        partner = self._get_or_create_candidate_partner()
        return self.env['bank.settlement.government.fee'].sudo().create({
            'government_entity_id': self.env.ref(
                'bank_settlement.government_entity_mol_resident').id,
            'fee_type_id': self.env.ref(
                'bank_settlement.government_fee_type_sponsorship_transfer').id,
            'amount': self.gov_fee_amount,
            'recruitment_request_id': self.id,
            'partner_id': partner.id,
            # الشركة صراحة من طلب التوظيف نفسه (مُشتقة أصلاً من المشروع/
            # المنصة المختارة) - بدل تركها تُحسب من الشركة النشطة لمن
            # يضغط زر "تسجيل الرسوم الحكومية"، والتي قد تختلف عن فرع
            # المشروع الفعلي.
            'company_id': self.company_id.id,
            'project_id': self.project_id.id,
            'transfer_date': fields.Date.context_today(self),
        }).id

    def action_view_import_request(self):
        self.ensure_one()
        if not self.import_request_id:
            raise UserError(_('لا يوجد طلب استقدام أصلي مرتبط.'))
        return {
            'name': _('طلب الاستقدام'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.import.request',
            'res_id': self.import_request_id.id,
            'view_mode': 'form',
        }

    def _apply_stage_side_effects(self):
        super()._apply_stage_side_effects()
        self.ensure_one()
        # طلب الاستقدام: الموظف أُنشئ مبكراً في "طلب استقدام" ببيانات
        # أساسية فقط - مرحلة "تم نقل الكفالة" (التي تنشئ الموظف عادة)
        # متخطاة بالكامل له، فنزامن هنا بدلاً منها الحقول الإضافية
        # (الجنسية/الحالة الاجتماعية/الجواز/المشروع/الوظيفة/القسم...) فور
        # اكتمالها: عند مغادرة "طلب جديد" (تُعبَّأ هناك) وتحديد المشروع في
        # "مراجعة مسؤول المشروع" - أي عند الدخول إلى "مراجعة مدير
        # العمليات" التالية لها مباشرة، تكون كل الحقول متوفرة معاً.
        if self.stage_id.code == 'operations_review' and self.is_import_request:
            self._sync_employee_extra_fields()

    def _sync_employee_extra_fields(self):
        """يكتب الحقول الإضافية (غير الأساسية الأربعة) من طلب التوظيف على
        سجل الموظف الموجود مسبقاً - انظر شرح الاستدعاء في
        _apply_stage_side_effects أعلاه. تستخدم بالضبط نفس خريطة الحقول
        المستخدمة في _create_employee() العادية (_build_employee_vals)،
        التي لن تُستدعى أصلاً لهذه الطلبات (employee_id موجود مسبقاً)."""
        self.ensure_one()
        if not (self.is_import_request and self.employee_id):
            return
        employee = self.employee_id.sudo()
        vals = self._build_employee_vals()
        # الاسم/جهة الاتصال مضبوطان ومطابقان مسبقاً من "طلب استقدام" - لا
        # داعي لإعادة كتابتهما هنا. project_id ممنوع كتابته مباشرة عبر
        # write() أصلاً (hr_employee.write() يرفضه بقصد - انظر شرحه هناك)،
        # فهو يُضبط حصراً عبر _open_platform_history() أدناه، وهي البوابة
        # الوحيدة المخوَّلة لتغييره.
        vals.pop('name', None)
        vals.pop('work_contact_id', None)
        vals.pop('project_id', None)
        if vals:
            employee.write(vals)

        if self.project_id and 'project_id' in employee._fields \
                and hasattr(employee, '_open_platform_history'):
            employee._open_platform_history(
                self.project_id,
                note=_('فتح تلقائي عند تعبئة بيانات المشروع لطلب استقدام %s') % self.name,
            )

        try:
            self._create_employee_bank_account(employee)
        except Exception:
            self.message_post(body=_(
                'تعذّر ربط الحساب البنكي تلقائياً بعد تعبئة بيانات الاستقدام. '
                'يُرجى إضافة الآيبان يدوياً في سجل الموظف.'
            ))

    def _create_employee(self):
        employee = super()._create_employee()
        self.ensure_one()
        if self.bank_settlement_gov_fee_id and not self.bank_settlement_gov_fee_id.employee_id:
            # يتجاوز قفل "لا تعديل بعد الاعتماد" عمداً - هذا استكمال
            # لنفس المرشّح المعتمَد أصلاً، وليس تغييراً فعلياً لهوية من
            # يخصّه السداد (انظر bank_settlement_mixin.write()).
            self.bank_settlement_gov_fee_id.with_context(
                bank_settlement_skip_approval_lock=True,
            ).write({
                'employee_id': employee.id,
                'partner_id': employee._get_personal_partner().id,
            })
        return employee
