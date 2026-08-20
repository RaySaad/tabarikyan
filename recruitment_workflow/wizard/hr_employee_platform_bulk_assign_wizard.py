# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeePlatformBulkAssignWizard(models.TransientModel):
    _name = 'hr.employee.platform.bulk.assign.wizard'
    _description = 'ربط عدة موظفين قدامى بمنصة دفعة واحدة'

    line_ids = fields.One2many(
        'hr.employee.platform.bulk.assign.wizard.line',
        'wizard_id',
        string='الموظفون',
    )
    employee_count = fields.Integer(
        string='عدد الموظفين',
        compute='_compute_employee_count',
    )
    project_id = fields.Many2one(
        'project.project',
        string='المنصة / المشروع',
        required=True,
        options="{'no_create': True}",
    )
    note = fields.Char(
        string='ملاحظة',
        help='تُسجَّل في سجل تاريخ المنصات لكل موظف (مثال: "ربط رجعي - بيانات قديمة").',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            employee_ids = self.env.context.get('active_ids')
            if employee_ids:
                # sudo(): حتى قراءة حقل عام كـcreate_date تفشل هنا بـ
                # AccessError - دفعة الجلب المسبق (prefetch) لسجل hr.employee
                # تشمل حقولاً خاصة مخصَّصة (project_id، analytic_account_id)
                # دائماً، فتفشل الدفعة كاملة لمن لا يملك hr.group_hr_user
                # حتى لو طُلب حقل عام واحد فقط.
                employees = self.env['hr.employee'].sudo().browse(employee_ids)
                res['line_ids'] = [
                    (0, 0, {
                        'employee_id': employee.id,
                        # تاريخ إنشاء سجل الموظف يعكس تاريخ تعيينه الفعلي
                        # لهؤلاء الموظفين القدامى - يبقى قابلاً للتعديل يدوياً.
                        'date_start': employee.create_date.date()
                        if employee.create_date else fields.Date.context_today(self),
                    })
                    for employee in employees
                ]
        return res

    @api.depends('line_ids')
    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.line_ids)

    def action_confirm_assign(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('لم يتم تحديد أي موظف.'))
        if any(not line.employee_id for line in self.line_ids):
            raise UserError(_(
                'يوجد سطر بدون موظف محدد - احذفه قبل التأكيد.'
            ))
        # هذا المعالج مخصَّص لربط موظفين قدامى ليس لهم منصة أصلاً (بيانات
        # رجعية) - وليس لنقل موظفين يعملون فعلاً على منصة أخرى، الذي يجب
        # أن يمر بخط سير طلب النقل (موافقة مسؤول المنصة الحالية ثم مدير
        # العمليات). بدون هذا التحقق، يصبح بالإمكان تجاوز خط السير بالكامل
        # عبر تحديد عدة موظفين دفعة واحدة من قائمة الموظفين وتحويلهم
        # فوراً بلا أي موافقة - إعادة تأكيد نفس المنصة الحالية للموظف
        # تبقى مسموحة (لا تغيير فعلي، ولا داعي لموافقة عليها).
        # sudo(): project_id حقل "خاص" من منظور hr.employee.public - مسؤول
        # المشروع (المخوَّل بهذا المعالج) لا يملك بالضرورة hr.group_hr_user.
        already_on_other_platform = self.line_ids.filtered(
            lambda l: l.employee_id.sudo().project_id
            and l.employee_id.sudo().project_id != self.project_id
        )
        if already_on_other_platform:
            raise UserError(_(
                'هذا المعالج مخصَّص لربط موظفين قدامى ليس لهم منصة أصلاً '
                'فقط. الموظف/الموظفون التالون يعملون بالفعل على منصة '
                'أخرى - استخدم "طلب نقل لمنصة أخرى" من سجل كل واحد منهم '
                'بدلاً من ذلك:\n%s'
            ) % '\n'.join(already_on_other_platform.mapped(lambda l: l.employee_id.sudo().name)))
        for line in self.line_ids:
            line.employee_id._open_platform_history(
                self.project_id, note=self.note, date_start=line.date_start,
            )
        return {'type': 'ir.actions.act_window_close'}


class HrEmployeePlatformBulkAssignWizardLine(models.TransientModel):
    _name = 'hr.employee.platform.bulk.assign.wizard.line'
    _description = 'سطر ربط موظف بمنصة (معالج الربط الجماعي)'

    wizard_id = fields.Many2one(
        'hr.employee.platform.bulk.assign.wizard',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='الموظف',
        # ليس required=True عمداً: الحقل readonly في الواجهة ولا يُملأ إلا
        # عبر default_get، لذا نتحقق من اكتماله بلطف في action_confirm_assign
        # بدل الاصطدام برسالة قيد NOT NULL العامة من قاعدة البيانات لو
        # وُجد سطر فارغ بأي شكل غير متوقع.
    )
    date_start = fields.Date(
        string='تاريخ بداية العمل على المنصة',
        required=True,
        default=fields.Date.context_today,
        help='مقترح تلقائياً من تاريخ تعيين الموظف (تاريخ إنشاء سجله)، '
             'ويمكن تعديله لكل موظف على حدة قبل التأكيد.',
    )
