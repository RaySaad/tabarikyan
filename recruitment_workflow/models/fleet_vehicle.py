# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    project_id = fields.Many2one(
        'project.project',
        string='المشروع / المنصة',
        help='المنصة التي تتبعها هذه السيارة ضمن الأسطول (اختياري). إن تُرك '
             'فارغاً، تكون السيارة متاحة لأي منصة عند طلب سيارة في التوظيف.',
    )
    branch_history_ids = fields.One2many(
        'fleet.vehicle.branch.history',
        'vehicle_id',
        string='تاريخ الفروع',
    )
    branch_history_count = fields.Integer(
        string='عدد فترات الفروع',
        compute='_compute_branch_history_count',
    )
    recruitment_state = fields.Selection(
        selection=[
            ('available', 'متاحة'),
            ('reserved', 'محجوزة (طلب توظيف)'),
            ('assigned', 'مخصصة'),
            ('unavailable', 'غير متاحة'),
        ],
        string='حالة التوفر للتوظيف',
        default='available',
        tracking=True,
        help='تحدد ما إذا كانت السيارة متاحة لتخصيصها في طلبات التوظيف.',
    )
    recruitment_request_ids = fields.One2many(
        'recruitment.request',
        'vehicle_id',
        string='طلبات التوظيف المرتبطة',
    )
    recruitment_request_count = fields.Integer(
        string='عدد الطلبات',
        compute='_compute_recruitment_request_count',
    )

    @api.depends('recruitment_request_ids')
    def _compute_recruitment_request_count(self):
        for rec in self:
            rec.recruitment_request_count = len(rec.recruitment_request_ids)

    @api.depends('branch_history_ids')
    def _compute_branch_history_count(self):
        for rec in self:
            rec.branch_history_count = len(rec.branch_history_ids)

    def action_set_available(self):
        self.write({'recruitment_state': 'available'})

    def action_set_unavailable(self):
        self.write({'recruitment_state': 'unavailable'})

    def _open_branch_history(self, company, note=False, date_start=None):
        """يفتح فترة جديدة في تاريخ الفروع ويغلق الفترة المفتوحة الحالية
        (إن وُجدت)، ثم يحدّث فرع/شركة السيارة الحالية - نفس مبدأ
        hr.employee._open_platform_history تماماً، لكن للفروع بدل المنصات.
        تنفيذ فوري بلا خط سير موافقة (بعكس نقل المنصة للمناديب) - طلب صريح:
        زر مباشر مع تسجيل الحركة فقط، وليس خط سير موافقة."""
        self.ensure_one()
        if not company:
            return False
        date_start = date_start or fields.Date.context_today(self)
        open_lines = self.branch_history_ids.filtered(lambda l: not l.date_end)
        # لا داعي لفتح فترة جديدة إن كان نفس الفرع الحالي بدون تغيير فعلي
        if open_lines and open_lines[0].company_id.id == company.id:
            return open_lines[0]
        open_lines.write({'date_end': date_start})
        new_line = self.env['fleet.vehicle.branch.history'].sudo().create({
            'vehicle_id': self.id,
            'company_id': company.id,
            'date_start': date_start,
            'note': note or False,
        })
        self.company_id = company.id
        self.message_post(body=_(
            'تم نقل السيارة إلى الفرع: %s%s'
        ) % (company.display_name, (' — %s' % note) if note else ''))
        return new_line

    def action_open_branch_transfer_wizard(self):
        self.ensure_one()
        return {
            'name': _('نقل لفرع آخر'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.branch.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_branch_history(self):
        self.ensure_one()
        return {
            'name': _('تاريخ الفروع - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle.branch.history',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }
