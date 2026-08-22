# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
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

    def write(self, vals):
        # المنصة الحالية لا يجوز تعديلها إلا عبر _open_platform_history -
        # البوابة الوحيدة المستخدمة من كل المسارات المخوَّلة (مباشرة العمل
        # الأولى من طلب التوظيف، الربط الجماعي للموظفين القدامى، واعتماد
        # طلب نقل المنصة). أي محاولة تعديل مباشرة لهذا الحقل (شاشة الموظف،
        # تعديل جماعي من القائمة، استيراد بيانات، أو RPC مباشر) تعني تجاوز
        # خط سير الموافقة بالكامل رغم إخفاء/تعطيل الزر في الواجهة فقط.
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

