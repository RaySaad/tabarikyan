# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'recruitment.workflow.analytic.mixin']

    project_id = fields.Many2one(
        'project.project',
        string='المنصة الحالية',
        tracking=True,
        # readonly في الواجهة فقط (انظر hr_employee_views.xml) - الحماية
        # الفعلية من جهة الخادم في write() أدناه، وإلا يبقى الحقل قابلاً
        # للتعديل المباشر عبر قائمة الموظفين (تعديل جماعي/inline)، الاستيراد،
        # أو RPC مباشر - متجاوزاً خط سير الموافقة بالكامل رغم إخفاء الزر.
        help='المشروع/المنصة الحالية التي يعمل عليها المندوب (كيتا، '
             'هنقرستيشن...). تُستخدم لفصل المتابعة والحسابات لكل منصة. '
             'لا يمكن تعديلها مباشرة - استخدم زر "طلب نقل لمنصة أخرى" '
             '(يمر بخط سير موافقة، مع الاحتفاظ بالتاريخ الكامل).',
    )
    platform_history_ids = fields.One2many(
        'hr.employee.platform.history',
        'employee_id',
        string='تاريخ المنصات',
    )
    platform_history_count = fields.Integer(
        string='عدد فترات المنصات',
        compute='_compute_platform_history_count',
    )
    transfer_request_ids = fields.One2many(
        'hr.employee.platform.transfer.request', 'employee_id',
        string='طلبات نقل المنصة',
    )
    pending_transfer_request_count = fields.Integer(
        string='طلبات نقل معلّقة',
        compute='_compute_pending_transfer_request_count',
    )
    # رقم جوال أبشر: يختلف عملياً عن جوال العمل/الجوال الشخصي المعياريين -
    # هو الرقم المسجَّل لدى أبشر باسم المندوب، والمستخدَم في تفويض
    # المركبات ونقل الملكية إلكترونياً، وقد يكون رقماً ثالثاً مختلفاً عن
    # الاثنين. groups='' غير مطلوب هنا (حقل من إنشائنا، غير موروث من
    # حقول hr المقيّدة).
    absher_mobile = fields.Char(
        string='رقم جوال أبشر', tracking=True,
        help='الرقم المسجَّل في أبشر باسم المندوب - يُستخدَم في تفويض '
             'المركبات إلكترونياً، وقد يختلف عن جوال العمل/الجوال الشخصي.',
    )
    vehicle_change_request_ids = fields.One2many(
        'fleet.vehicle.change.request', 'employee_id',
        string='طلبات تغيير المركبة',
    )
    warning_ids = fields.One2many(
        'hr.employee.warning', 'employee_id', string='الإنذارات',
    )
    active_warning_count = fields.Integer(
        string='الإنذارات السارية', compute='_compute_active_warning_count',
        help='الإنذارات المعتمدة التي لم تسقط بالتقادم - وهي وحدها '
             'المحتسبة في تصعيد أي إنذار جديد.',
    )
    exit_request_ids = fields.One2many(
        'hr.employee.exit.request', 'employee_id', string='طلبات إنهاء الخدمة',
    )
    vehicle_change_request_count = fields.Integer(
        string='عدد طلبات تغيير المركبة',
        compute='_compute_vehicle_change_request_count',
    )
    @api.depends('platform_history_ids')
    def _compute_platform_history_count(self):
        for rec in self:
            rec.platform_history_count = len(rec.platform_history_ids)

    @api.depends('transfer_request_ids.state')
    def _compute_pending_transfer_request_count(self):
        for rec in self:
            rec.pending_transfer_request_count = len(rec.transfer_request_ids.filtered(
                lambda r: r.state not in ('done', 'cancel')
            ))

    @api.depends('vehicle_change_request_ids')
    def _compute_vehicle_change_request_count(self):
        for rec in self:
            rec.vehicle_change_request_count = len(rec.vehicle_change_request_ids)

    @api.depends('warning_ids.state', 'warning_ids.expiry_date')
    def _compute_active_warning_count(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.active_warning_count = len(rec.warning_ids.filtered(
                lambda w: w.state in ('confirmed', 'notified')
                and (not w.expiry_date or w.expiry_date >= today)
            ))

    def _close_platform_history(self, date_end):
        """يغلق فترة المنصة المفتوحة حالياً بلا فتح فترة جديدة - تُستخدَم
        عند إنهاء خدمة الموظف. بدونها تبقى الفترة مفتوحة للأبد فتُحمَّل
        على المنصة تكاليف موظف غادر (وتلتقطها آليات التوزيع التحليلي
        لاحقاً على أنها منصته "الحالية").

        sudo(): سجل تاريخ المنصات وحقل project_id حقلان داخليان محميان -
        من يعتمد إنهاء الخدمة (موارد بشرية/عمليات) لا يملك بالضرورة
        صلاحية الكتابة المباشرة عليهما."""
        self.ensure_one()
        employee = self.sudo()
        open_lines = employee.platform_history_ids.filtered(lambda h: not h.date_end)
        if open_lines:
            open_lines.write({'date_end': date_end})
        if employee.project_id:
            employee.with_context(platform_history_internal_write=True).project_id = False
        return True

    def action_view_warnings(self):
        self.ensure_one()
        return {
            'name': _('إنذارات - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.warning',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_exit_requests(self):
        self.ensure_one()
        return {
            'name': _('طلبات إنهاء الخدمة - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.exit.request',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def _get_current_vehicle(self):
        """المركبة المخصَّصة حالياً لهذا المندوب - عبر شريكه الشخصي، لأن
        أودو القياسية تربط السائق بالمركبة كشريك (driver_id) وليس كموظف.

        sudo(): البحث يمر عبر شريك الموظف الشخصي (حقل "خاص") وعلى
        fleet.vehicle المقيَّدة بقاعدة الشركات - وهذه قراءة تقنية داخلية
        بحتة (اشتقاق حقل) لا تعرض بيانات إضافية للمستخدم."""
        self.ensure_one()
        partner = self._get_personal_partner()
        if not partner:
            return self.env['fleet.vehicle']
        return self.env['fleet.vehicle'].sudo().search(
            [('driver_id', '=', partner.id)], limit=1,
        )

    def action_view_vehicle_change_requests(self):
        self.ensure_one()
        return {
            'name': _('طلبات تغيير المركبة - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.change.request',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    # ------------------------------------------------------------------
    # الإقامة: رقمها عندنا هو identification_id (انظر residency_number في
    # bank_settlement وfleet_vehicle_change_request، وحقل "رقم الهوية /
    # الإقامة" في طلب التوظيف) - وأودو لا تُقرن به تاريخ انتهاء إطلاقاً:
    # تواريخ الانتهاء القياسية عندها للتأشيرة (visa_expire) ورخصة العمل
    # (work_permit_expiration_date) والجواز فقط. فيُضاف هنا.
    # ------------------------------------------------------------------
    iqama_expiry_date = fields.Date(
        string='تاريخ انتهاء الإقامة', tracking=True,
        help='يُستخدم لبناء جدول "الدفعة المقدمة" لرسوم تجديد الإقامة '
             '(تبدأ التغطية في اليوم التالي له)، ولتنبيه الموارد البشرية '
             'قبل انتهائه بالمدة المحددة في الإعدادات.',
    )
    # يمنع تكرار التنبيه يومياً طوال نافذة المهلة. يُصفَّر تلقائياً عند
    # تغيّر التاريخ (تجديد جديد) فيُنبَّه عليه من جديد في موعده.
    iqama_expiry_activity_done = fields.Boolean(
        string='نُبّه على انتهاء الإقامة', default=False, copy=False,
    )

    @api.model
    def _cron_notify_iqama_expiry(self):
        """ينبّه الموارد البشرية قبل انتهاء إقامة كل مندوب.

        يستخدم "أقل من أو يساوي" لا "يساوي بالضبط" كما في تنبيه رخصة
        العمل بأودو: المطابقة التامة تعني أن يوماً واحداً لم تعمل فيه
        المهمة (تعطّل، أو بيئة لا تُشغّل المهام المجدولة) يُسقط تنبيه ذلك
        الموظف نهائياً بلا أثر. والراية تمنع التكرار اليومي بدلاً من ذلك.
        """
        today = fields.Date.context_today(self)
        Activity = self.env['mail.activity']
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not todo:
            return True
        for company in self.env['res.company'].sudo().search([]):
            notice = company.iqama_expiration_notice_period
            if notice <= 0:
                continue
            employees = self.sudo().search([
                ('company_id', '=', company.id),
                ('iqama_expiry_date', '!=', False),
                ('iqama_expiry_date', '<=', today + timedelta(days=notice)),
                ('iqama_expiry_activity_done', '=', False),
            ])
            for employee in employees:
                user = employee._get_iqama_notice_user()
                if not user:
                    continue
                employee.with_context(mail_activity_quick_update=True).activity_schedule(
                    'mail.mail_activity_data_todo',
                    employee.iqama_expiry_date,
                    _('إقامة %(name)s تنتهي في %(date)s - يلزم التجديد.') % {
                        'name': employee.name, 'date': employee.iqama_expiry_date,
                    },
                    user_id=user.id,
                )
                employee.iqama_expiry_activity_done = True
        return True

    def _get_iqama_notice_user(self):
        """وجهة التنبيه: مسؤول الموارد البشرية للموظف، بشرط أن يكون فعلاً
        من الموارد البشرية - وإلا فأول مدير موارد بشرية في نفس الشركة.

        شرط الصلاحية ليس تزيّداً: hr_responsible_id حقل مطلوب في أودو 19
        فتضعه أودو تلقائياً على مُنشئ السجل - وقد يكون موظف إدخال بيانات
        أو مدير مباشر لا علاقة له بتجديد الإقامات، فيذهب التنبيه لمن لا
        يملك حتى فتح تبويب البيانات الشخصية. والتنبيه مطلوب للموارد
        البشرية تحديداً.

        وبعكس أودو التي ترجع لمستخدم المهمة المجدولة (OdooBot) عند غياب
        المسؤول - فينتهي التنبيه في صندوق لا يقرأه أحد."""
        self.ensure_one()
        responsible = self.sudo().hr_responsible_id
        if responsible and responsible.active and responsible.has_group('hr.group_hr_user'):
            return responsible
        for xmlid in ('hr.group_hr_manager', 'hr.group_hr_user'):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            user = group.sudo().all_user_ids.filtered(
                lambda u: u.active and (
                    not self.company_id or self.company_id in u.company_ids)
            )[:1]
            if user:
                return user
        return self.env['res.users']

    def write(self, vals):
        # المنصة الحالية لا يجوز تعديلها إلا عبر _open_platform_history -
        # البوابة الوحيدة المستخدمة من كل المسارات المخوَّلة (مباشرة العمل
        # الأولى من طلب التوظيف، الربط الجماعي للموظفين القدامى، واعتماد
        # طلب نقل المنصة). أي محاولة تعديل مباشرة لهذا الحقل (شاشة الموظف،
        # تعديل جماعي من القائمة، استيراد بيانات، أو RPC مباشر) تعني تجاوز
        # خط سير الموافقة بالكامل رغم إخفاء/تعطيل الزر في الواجهة فقط.
        # تغيّر تاريخ انتهاء الإقامة (تجديد جديد) يُعيد فتح باب التنبيه.
        if 'iqama_expiry_date' in vals:
            vals.setdefault('iqama_expiry_activity_done', False)
        if 'project_id' in vals and not self.env.context.get(
            'platform_history_internal_write'
        ):
            raise UserError(_(
                'لا يمكن تعديل "المنصة الحالية" مباشرة.\n'
                'استخدم زر "طلب نقل لمنصة أخرى" في سجل الموظف - يمر بخط '
                'سير موافقة (مسؤول المنصة الحالية ثم مدير العمليات) بدل '
                'التعديل المباشر.'
            ))
        return super().write(vals)

    def unlink(self):
        # حذف سجل الموظف نهائياً يقطع الرابط الرسمي مع سجلات تدقيق دائمة
        # (طلب التوظيف الأصلي، تاريخ المنصات، التكاليف، طلبات النقل) يُمنع
        # حذفها هي نفسها صراحة في كل مكان آخر بالنظام - فالسماح بحذف الموظف
        # نفسه يُبطل تلك الحماية كلها من الخلف. ثغرة حقيقية سبّبت فقدان
        # بيانات فعلياً (بلاغ مستخدم: حُذف موظف له سلفة "بانتظار الموافقة"
        # في bank_settlement، فتعطّلت الشاشة تماماً). الأرشفة (زر "أرشفة")
        # هي البديل الصحيح دائماً لموظف غادر الشركة أو أُنشئ بالخطأ.
        # (اسم الموديل، اسم الحقل، الوصف الظاهر في الرسالة) - نفس الأربعة
        # التي تحمي نفسها من الحذف المباشر فعلياً في كل مكان آخر بالنظام؛
        # نفحصها هنا مسبقاً برسالة عربية واضحة بدل الاعتماد فقط على قيد
        # ondelete='restrict' على مستوى قاعدة البيانات (يبقى فعّالاً كخط
        # حماية أخير حتى لو نسينا إضافة نموذج جديد هنا مستقبلاً).
        linked_models = [
            ('recruitment.request', 'employee_id', 'طلب/طلبات توظيف'),
            ('hr.employee.platform.history', 'employee_id', 'سجل/سجلات تاريخ منصات'),
            ('hr.employee.platform.transfer.request', 'employee_id', 'طلب/طلبات نقل منصة'),
            ('fleet.vehicle.change.request', 'employee_id', 'طلب/طلبات تغيير مركبة'),
            ('fleet.accident.report', 'employee_id', 'بلاغ/بلاغات حوادث'),
            ('hr.employee.warning', 'employee_id', 'إنذار/إنذارات'),
            ('hr.employee.exit.request', 'employee_id', 'طلب/طلبات إنهاء خدمة'),
        ]
        for employee in self:
            for model_name, field_name, description in linked_models:
                Model = self.env[model_name].sudo()
                if Model.search_count([(field_name, '=', employee.id)]):
                    raise UserError(_(
                        'لا يمكن حذف الموظف "%(employee)s" نهائياً - له '
                        '%(description)s مرتبطة به يجب الحفاظ على سجلها '
                        'للتدقيق. استخدم "أرشفة" بدلاً من الحذف.'
                    ) % {'employee': employee.name, 'description': description})
        return super().unlink()

    def _open_platform_history(self, project, note=False, date_start=None):
        """يفتح فترة جديدة في تاريخ المنصات ويغلق الفترة المفتوحة الحالية
        (إن وُجدت)، ثم يحدّث المنصة الحالية للمندوب.

        تُستخدم هذه الدالة سواء عند أول تعيين للمندوب (من طلب التوظيف) أو
        عند نقله لاحقاً بين المنصات، مع الحفاظ الكامل على السجل التاريخي.

        :param date_start: تاريخ بداية الفترة الجديدة - يُفترض اليوم إن لم
            يُحدَّد. مهم عند الربط الرجعي لموظفين قدامى كانوا على المنصة
            فعلياً منذ تاريخ سابق، وليس منذ اليوم.

        sudo() ضروري هنا: platform_history_ids حقل "خاص" من منظور
        hr.employee (غير مُدرَج في hr.employee.public)، وhr.employee نفسه
        لا يملك أي مستخدم بمجموعات موديول التوظيف فقط (بلا hr.group_hr_user)
        صلاحية قراءة/كتابة عليه مباشرة عبر ir.model.access - رغم أن هذه
        الدالة تُستدعى تحديداً من action_confirm_transfer المخصصة لمجموعة
        "مدير العمليات" (recruitment_workflow) - ثغرة حقيقية اكتُشفت
        بالاختبار الفعلي."""
        self.ensure_one()
        if not project:
            return False
        employee = self.sudo()
        # نضمن وجود حساب تحليلي على المنصة الجديدة هنا بالذات - لحظة النقل
        # الفعلية لموديول التوظيف - قبل ما نعتمد عليه بمزامنة العقد بالأسفل.
        if not project.account_id:
            project._create_default_analytic_account()
        date_start = date_start or fields.Date.context_today(self)
        open_lines = employee.platform_history_ids.filtered(lambda l: not l.date_end)
        # لا داعي لفتح فترة جديدة إن كانت نفس المنصة الحالية بدون تغيير فعلي
        if open_lines and open_lines[0].project_id.id == project.id:
            return open_lines[0]
        open_lines.write({'date_end': date_start})
        new_line = self.env['hr.employee.platform.history'].sudo().create({
            'employee_id': self.id,
            'project_id': project.id,
            'date_start': date_start,
            'note': note or False,
        })
        employee.with_context(platform_history_internal_write=True).project_id = project.id
        employee._sync_contract_project()
        employee._sync_partner_analytic_distribution(project)
        employee.message_post(body=_(
            'تم نقل المندوب إلى المنصة: %s%s'
        ) % (project.display_name, (' — %s' % note) if note else ''))
        return new_line

    def _get_personal_partner(self):
        """يجد partner المندوب الشخصي (وليس partner العمل/الشركة) بنفس
        الترتيب الاحتياطي المستخدم في recruitment_request.py.

        sudo() ضروري هنا: work_contact_id/address_home_id حقلان "خاصان"
        (Private) من منظور hr.employee (غير مُدرَجين في hr.employee.public)
        - بلا sudo() كان أي مستدعٍ من مستخدم بلا hr.group_hr_user (مثل
        محاسب/مدير عام السداد البنكي عند إتمام الصرف) سيفشل بـ AccessError
        فور الوصول لهذه الدالة، رغم أنها إرجاع تقني بحت لمعرّف شريك
        محاسبي (لا تعرض بيانات الموظف الشخصية للمستدعي نفسه) - ثغرة
        حقيقية مكتشفة بالاختبار الفعلي."""
        self.ensure_one()
        employee = self.sudo()
        if 'work_contact_id' in employee._fields and employee.work_contact_id:
            return employee.work_contact_id
        if 'address_home_id' in employee._fields and employee.address_home_id:
            return employee.address_home_id
        if employee.user_id and employee.user_id.partner_id:
            return employee.user_id.partner_id
        return self.env['res.partner']

    def _sync_partner_analytic_distribution(self, project):
        """يحدّث (أو ينشئ) نموذج توزيع تحليلي (account.analytic.distribution
        .model) لشريك المندوب الشخصي، بحيث يُقترح حساب المنصة الحالية
        تلقائياً على أي فاتورة/قيد محاسبي مستقبلي يُنشأ لهذا الشريك تحديداً
        (خصم، غرامة، مستحقات...) - بدل إدخاله يدوياً في كل مرة. يُستدعى من
        نفس نقطة تحديث المنصة (_open_platform_history) ليبقى متزامناً مع
        كل نقل بين المنصات تلقائياً.
        """
        self.ensure_one()
        partner = self._get_personal_partner()
        if not partner or not project.account_id:
            return
        Model = self.env['account.analytic.distribution.model'].sudo()
        distribution = {str(project.account_id.id): 100.0}
        existing = Model.search([('partner_id', '=', partner.id)], limit=1)
        if existing:
            existing.write({
                'analytic_distribution': distribution,
                'company_id': project.company_id.id,
            })
        else:
            Model.create({
                'partner_id': partner.id,
                'analytic_distribution': distribution,
                'company_id': project.company_id.id,
            })

    def _sync_contract_project(self):
        """يحدّث حقل المشروع/المنصة على عقد الموظف الحالي (hr.version أو
        hr.contract) بعد كل تعيين أو نقل منصة، إن كان الحقل متوفراً.

        ملاحظة: لا نحاول ربط حساب تحليلي على العقد هنا - تحقّقنا على بيئة
        Odoo Enterprise Payroll الفعلية أن لا يوجد حقل تحليلي على العقد/
        الإصدار إطلاقاً؛ التوزيع التحليلي للرواتب هناك يُدار على مستوى
        قواعد الراتب (Salary Rules) نفسها عند الترحيل المحاسبي.
        """
        self.ensure_one()
        contract = False
        for fname in ('current_version_id', 'version_id'):
            if fname in self._fields and self[fname]:
                contract = self[fname]
                break
        if not contract:
            for model_name in ('hr.version', 'hr.contract'):
                if model_name in self.env and 'employee_id' in self.env[model_name]._fields:
                    contract = self.env[model_name].sudo().search(
                        [('employee_id', '=', self.id)], limit=1, order='id desc',
                    )
                    if contract:
                        break
        if not contract:
            return False

        if 'project_id' in contract._fields and self.project_id:
            contract.sudo().project_id = self.project_id.id
        return True

    def action_open_platform_transfer_request(self):
        """يفتح نموذج "طلب نقل" جديد (وليس تنفيذ النقل فوراً) - يمر
        الطلب بخط سير موافقة (مسؤول المنصة الحالية ثم مدير العمليات)
        قبل تنفيذ النقل الفعلي. انظر hr_employee_platform_transfer_request.py."""
        self.ensure_one()
        return {
            'name': _('طلب نقل لمنصة أخرى'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.platform.transfer.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.id,
                'default_current_project_id': self.project_id.id,
            },
        }

    def action_view_transfer_requests(self):
        self.ensure_one()
        return {
            'name': _('طلبات نقل المنصة - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.platform.transfer.request',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_platform_history(self):
        self.ensure_one()
        return {
            'name': _('تاريخ المنصات - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.platform.history',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

