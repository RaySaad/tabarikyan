# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RecruitmentReturnWizard(models.TransientModel):
    _name = 'recruitment.return.wizard'
    _description = 'مساعد إرجاع طلب التوظيف لمرحلة سابقة'

    request_id = fields.Many2one(
        'recruitment.request',
        string='الطلب',
        required=True,
    )
    target_stage_id = fields.Many2one(
        'recruitment.stage',
        string='الإرجاع إلى مرحلة',
        required=True,
        help='اختر المرحلة السابقة التي تريد إرجاع الطلب إليها للتصحيح.',
    )
    reason = fields.Text(
        string='سبب الإرجاع',
        required=True,
        help='وضّح البيانات الناقصة أو غير الصحيحة المطلوب تصحيحها.',
    )
    available_stage_ids = fields.Many2many(
        'recruitment.stage',
        string='المراحل المتاحة',
        compute='_compute_available_stages',
    )

    @api.depends('request_id.stage_id')
    def _compute_available_stages(self):
        for rec in self:
            req = rec.request_id
            if not req or not req.stage_id:
                rec.available_stage_ids = False
                continue
            # المراحل السابقة فقط (ترتيب أقل من المرحلة الحالية)
            prev_stages = self.env['recruitment.stage'].search([
                ('sequence', '<', req.stage_id.sequence),
            ])
            rec.available_stage_ids = prev_stages

    def action_confirm_return(self):
        self.ensure_one()
        if not self.reason:
            raise UserError(_('يجب إدخال سبب الإرجاع.'))
        if not self.target_stage_id:
            raise UserError(_('يجب اختيار المرحلة المراد الإرجاع إليها.'))
        if self.target_stage_id.sequence >= self.request_id.stage_id.sequence:
            raise UserError(_('يجب اختيار مرحلة سابقة للمرحلة الحالية.'))
        self.request_id.action_return_to_stage(
            self.target_stage_id, self.reason,
        )
        return {'type': 'ir.actions.act_window_close'}
