# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetVehicleBranchHistory(models.Model):
    """سجل تاريخ تبعية السيارة للفروع - نفس مبدأ hr.employee.platform.history
    تماماً (فترات متتالية بتاريخ بداية/نهاية)، لكن للفرع/الشركة التابعة لها
    السيارة بدل المنصة التي يعمل عليها المندوب."""
    _name = 'fleet.vehicle.branch.history'
    _description = 'سجل تاريخ فروع السيارة'
    _order = 'date_start desc, id desc'
    _rec_name = 'company_id'

    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='السيارة',
        required=True,
        ondelete='cascade',
        index=True,
    )
    # هذا الحقل يمثّل في آن واحد: (1) الفرع الفعلي الذي كانت السيارة
    # تابعة له خلال هذه الفترة، و(2) نطاق العزل متعدد الشركات لهذا السجل
    # نفسه عبر ir.rule (fleet_vehicle_branch_history_company_rule) - بعكس
    # hr.employee.platform.history التي احتاجت حقل شركة منفصلاً لأن
    # "المنصة" هناك (project.project) مفهوم مختلف عن "الشركة/الفرع".
    company_id = fields.Many2one(
        'res.company',
        string='الفرع / الشركة',
        required=True,
        index=True,
    )
    date_start = fields.Date(string='تاريخ البداية', required=True)
    date_end = fields.Date(
        string='تاريخ النهاية',
        help='يبقى فارغاً طالما السيارة لا تزال تابعة لهذا الفرع حالياً.',
    )
    is_current = fields.Boolean(
        string='الفترة الحالية',
        compute='_compute_is_current',
        store=True,
    )
    note = fields.Char(string='ملاحظة النقل')
    moved_by = fields.Many2one(
        'res.users', string='نُقلت بواسطة',
        default=lambda self: self.env.user,
    )

    @api.depends('date_end')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.date_end

    def unlink(self):
        # سجل تاريخ الفروع هو المرجع الرسمي الدائم لمعرفة أي فرع كانت تتبعه
        # السيارة ومتى - نفس مبدأ hr.employee.platform.history/
        # recruitment_request.unlink() تماماً: يُمنع حذفه نهائياً حتى لمدير
        # سير العمل، وإلا أمكن محو فترة تاريخية كاملة بلا أي أثر. تصحيح خطأ
        # يجب أن يمر عبر نقل جديد يفتح فترة صحيحة، وليس حذف الفترة الخاطئة.
        raise UserError(_(
            'لا يمكن حذف سجلات تاريخ الفروع نهائياً، للحفاظ على سجل تدقيق '
            'ومراجعة كامل. أنشئ عملية نقل جديدة لتصحيح الفترة الحالية إن '
            'احتجت ذلك.'
        ))
