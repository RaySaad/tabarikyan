# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class BankSettlementMedicalInsurance(models.Model):
    """التأمين الطبي — مرتبط بمورد (Vendor) كما ظهر في الفيديو."""
    _name = 'bank.settlement.medical.insurance'
    _description = 'تأمين / فحص طبي'
    _inherit = ['bank.settlement.mixin']

    fee_type = fields.Selection(
        selection=[
            ('medical_insurance', 'تأمين طبي'),
            ('medical_checkup', 'فحص طبي'),
        ],
        string='نوع الرسوم', required=True, tracking=True,
    )
    vendor_id = fields.Many2one(
        'res.partner', string='المورد', domain=[('supplier_rank', '>', 0)],
        tracking=True,
    )
    company_iban = fields.Char(string='آيبان الشركة')

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'تم التحويل'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.medical.insurance'

    def action_create_insurance_transfer(self):
        """ينشئ فاتورة مورد (Vendor Bill) فعلية على المورد المحدَّد، بدل
        القيد اليدوي العام المستخدم في بقية النماذج - لأن التأمين الطبي
        مرتبط بمورد حقيقي له فاتورة رسمية. ينهي دورة الحالة أيضاً (كانت
        سابقاً لا تصل لحالة "تم التحويل" لعدم تحديث state هنا إطلاقاً)."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError('يجب تأكيد السجل أولاً قبل إنشاء تحويل التأمين.')
        self._check_group(
            'bank_settlement.group_bank_settlement_reviewer',
            'bank_settlement.group_bank_settlement_manager',
        )
        if not self.vendor_id:
            raise UserError('يجب تحديد المورد أولاً لإنشاء تحويل التأمين.')
        # sudo(): نفس منطق _create_settlement_move في المixin - لا يجوز أن
        # يشترط إنشاء الفاتورة عضوية محاسبية أصلية بـ Odoo؛ الصلاحية الفعلية
        # محكومة بالفعل عبر _check_group أعلاه.
        move = self.env['account.move'].sudo().create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor_id.id,
            # الشركة صراحة من شركة السجل نفسها - بدل تركها تُحسب من الشركة
            # النشطة لمن يضغط الزر (انظر نفس المنطق في _create_settlement_move).
            'company_id': self.company_id.id,
            # يُستخدم لحصر رؤية "مستخدم/مراجع" السداد البنكي على قيودهم فقط
            # عبر ir.rule - دون كشف بقية فواتير الشركة.
            'is_bank_settlement_move': True,
            'ref': self.name,
            'invoice_date': self.transfer_date or fields.Date.context_today(self),
            'invoice_line_ids': [(0, 0, {
                'name': self.name,
                'quantity': 1,
                'price_unit': self.total_amount,
                'analytic_distribution': (
                    {str(self.analytic_account_id.id): 100}
                    if self.analytic_account_id else False
                ),
            })],
        })
        self.move_id = move.id
        self.state = 'done'
        return move.id
