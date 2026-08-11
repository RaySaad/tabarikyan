# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class BankSettlementAdvance(models.Model):
    """السلف — كود REQ/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.advance'
    _description = 'سلفة موظف'
    _inherit = ['bank.settlement.mixin']

    advance_reason = fields.Selection(
        selection=[
            ('salary_advance', 'سلفة راتب'),
            ('emergency', 'طارئة'),
        ],
        string='سبب السلفة', required=True, tracking=True,
    )

    # حالة خاصة بالسلف كما ظهرت بالفيديو: بانتظار الموافقة / تمت الموافقة / تم الصرف
    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('waiting_approval', 'بانتظار الموافقة'),
            ('approved', 'تمت الموافقة'),
            ('paid', 'تم الصرف'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.advance'

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('يمكن إرسال السلف في حالة "مسودة" فقط للمراجعة.')
        self.write({'state': 'waiting_approval'})

    def action_confirm(self):
        """الموافقة على السلفة - تقتصر على المدير العام."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise UserError('يمكن الموافقة على السلف في حالة "بانتظار الموافقة" فقط.')
            rec._check_group('bank_settlement.group_bank_settlement_manager')
        self.write({'state': 'approved'})

    def action_done(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError('يجب الموافقة على السلفة أولاً قبل صرفها.')
            rec._check_group(
                'bank_settlement.group_bank_settlement_reviewer',
                'bank_settlement.group_bank_settlement_manager',
            )
            if not rec.move_id:
                rec.move_id = rec._create_settlement_move()
        self.write({'state': 'paid'})

    def action_reset_draft(self):
        for rec in self:
            if rec.move_id:
                raise UserError(
                    'لا يمكن إعادة هذه السلفة لمسودة - يوجد قيد محاسبي مرتبط '
                    'بها بالفعل (%s). ألغِ/اعكس القيد أولاً من المحاسبة.'
                    % rec.move_id.name
                )
        self.write({'state': 'draft'})

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(
                    'لا يمكن إلغاء هذه السلفة - القيد المحاسبي المرتبط بها '
                    'مرحّل بالفعل (%s). ألغِه/اعكسه من المحاسبة أولاً.'
                    % rec.move_id.name
                )
        self.write({'state': 'cancel'})
