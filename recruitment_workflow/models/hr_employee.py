# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = ['hr.employee', 'recruitment.workflow.analytic.mixin']

    project_id = fields.Many2one(
        'project.project',
        string='المنصة الحالية',
        tracking=True,
        help='المشروع/المنصة الحالية التي يعمل عليها المندوب (كيتا، '
             'هنقرستيشن...). تُستخدم لفصل المتابعة والحسابات لكل منصة. '
             'استخدم زر "نقل لمنصة أخرى" لتغييرها مع الاحتفاظ بالتاريخ.',
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
    cost_ids = fields.One2many(
        'hr.employee.cost',
        'employee_id',
        string='تكاليف مرتبطة بالمنصات',
    )
    cost_count = fields.Integer(
        string='عدد التكاليف',
        compute='_compute_cost_count',
    )
    total_posted_cost = fields.Monetary(
        string='إجمالي التكاليف المرحّلة',
        compute='_compute_cost_count',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='العملة',
        compute='_compute_currency_id',
    )

    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.depends('cost_ids.move_state', 'cost_ids.amount')
    def _compute_cost_count(self):
        for rec in self:
            rec.cost_count = len(rec.cost_ids)
            # "المرحّلة" تعني حالة الترحيل المحاسبي الفعلية لفاتورة المورد
            # المرتبطة (move_state == 'posted') - وليس حقل state الخاص بسير
            # عمل التكلفة نفسها (draft/submitted/cancelled)، الذي لا يملك
            # قيمة 'posted' إطلاقاً أصلاً.
            rec.total_posted_cost = sum(
                rec.cost_ids.filtered(lambda c: c.move_state == 'posted').mapped('amount')
            )

    @api.depends('platform_history_ids')
    def _compute_platform_history_count(self):
        for rec in self:
            rec.platform_history_count = len(rec.platform_history_ids)

    def _open_platform_history(self, project, note=False):
        """يفتح فترة جديدة في تاريخ المنصات ويغلق الفترة المفتوحة الحالية
        (إن وُجدت)، ثم يحدّث المنصة الحالية للمندوب.

        تُستخدم هذه الدالة سواء عند أول تعيين للمندوب (من طلب التوظيف) أو
        عند نقله لاحقاً بين المنصات، مع الحفاظ الكامل على السجل التاريخي.
        """
        self.ensure_one()
        if not project:
            return False
        # نضمن وجود حساب تحليلي على المنصة الجديدة هنا بالذات - لحظة النقل
        # الفعلية لموديول التوظيف - قبل ما نعتمد عليه بمزامنة العقد بالأسفل.
        if not project.account_id:
            project._create_default_analytic_account()
        today = fields.Date.context_today(self)
        open_lines = self.platform_history_ids.filtered(lambda l: not l.date_end)
        # لا داعي لفتح فترة جديدة إن كانت نفس المنصة الحالية بدون تغيير فعلي
        if open_lines and open_lines[0].project_id.id == project.id:
            return open_lines[0]
        open_lines.write({'date_end': today})
        new_line = self.env['hr.employee.platform.history'].sudo().create({
            'employee_id': self.id,
            'project_id': project.id,
            'date_start': today,
            'note': note or False,
        })
        self.project_id = project.id
        self._sync_contract_project()
        self.message_post(body=_(
            'تم نقل المندوب إلى المنصة: %s%s'
        ) % (project.display_name, (' — %s' % note) if note else ''))
        return new_line

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

    def action_open_platform_transfer_wizard(self):
        self.ensure_one()
        return {
            'name': _('نقل لمنصة أخرى'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.platform.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.id,
                'default_current_project_id': self.project_id.id,
            },
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

    def action_view_costs(self):
        self.ensure_one()
        return {
            'name': _('تكاليف المنصات - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.cost',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {
                'default_employee_id': self.id,
                'default_project_id': self.project_id.id,
            },
        }
