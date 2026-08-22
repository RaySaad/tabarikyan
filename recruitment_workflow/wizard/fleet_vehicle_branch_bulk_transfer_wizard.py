# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetVehicleBranchBulkTransferWizard(models.TransientModel):
    """نقل عدة سيارات لفرع آخر دفعة واحدة - نفس مبدأ fleet.vehicle.branch.
    transfer.wizard الفردي (تنفيذ فوري بلا موافقة، مع تسجيل الحركة في
    fleet.vehicle.branch.history تلقائياً لكل سيارة)، لكن لعدة سيارات معاً
    بفرع هدف واحد مشترك. طلب صريح: أغلب سيارات الأسطول مسجَّلة حالياً على
    الشركة الأم ولا يُعقل نقلها للفروع الفعلية واحدة تلو الأخرى."""
    _name = 'fleet.vehicle.branch.bulk.transfer.wizard'
    _description = 'نقل عدة سيارات لفرع آخر دفعة واحدة'

    vehicle_ids = fields.Many2many('fleet.vehicle', string='السيارات')
    vehicle_count = fields.Integer(
        string='عدد السيارات', compute='_compute_vehicle_count',
    )
    company_id = fields.Many2one(
        'res.company', string='نقل إلى فرع', required=True,
        options="{'no_create': True}",
    )
    note = fields.Char(
        string='ملاحظة',
        help='تُسجَّل في سجل تاريخ الفروع لكل سيارة منقولة.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'vehicle_ids' in fields_list and not res.get('vehicle_ids'):
            vehicle_ids = self.env.context.get('active_ids')
            if vehicle_ids:
                res['vehicle_ids'] = [(6, 0, vehicle_ids)]
        return res

    @api.depends('vehicle_ids')
    def _compute_vehicle_count(self):
        for rec in self:
            rec.vehicle_count = len(rec.vehicle_ids)

    def action_confirm_transfer(self):
        self.ensure_one()
        if not self.vehicle_ids:
            raise UserError(_('لم يتم تحديد أي سيارة.'))
        if not self.company_id:
            raise UserError(_('يجب اختيار الفرع المراد النقل إليه.'))
        # لا داعي لاستثناء السيارات التابعة أصلاً لهذا الفرع (بعكس المعالج
        # الفردي الذي يرفض ذلك صراحة) - في نقل جماعي يتوقع اختلاط سيارات
        # تحتاج نقلاً فعلياً مع أخرى منقولة مسبقاً ضمن نفس التحديد؛
        # _open_branch_history نفسها متكرِّرة الاستدعاء بأمان (idempotent):
        # لا تفتح فترة تاريخية جديدة إن كان الفرع الحالي مطابقاً أصلاً.
        for vehicle in self.vehicle_ids:
            vehicle._open_branch_history(self.company_id, self.note)
        return {'type': 'ir.actions.act_window_close'}
