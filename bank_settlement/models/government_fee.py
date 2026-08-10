# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class BankSettlementGovernmentFee(models.Model):
    """الرسوم الحكومية — كود Gov/Fee/xxxx كما ظهر في الفيديو."""
    _name = 'bank.settlement.government.fee'
    _description = 'رسوم حكومية'
    _inherit = ['bank.settlement.mixin']

    # TODO: تحويلها لاحقاً إلى Many2one على نموذج "الجهات الحكومية" مخصص
    # بدلاً من Selection إذا كانت القائمة طويلة/قابلة للتوسع من المستخدم
    government_entity = fields.Selection(
        selection=[
            ('mol_resident', 'وزارة الداخلية ( مقيم )'),
            ('hrsd_expat', 'وزارة التنمية و الموارد البشرية ( قوى & أجير )'),
        ],
        string='الجهة الحكومية', required=True, tracking=True,
    )
    fee_type = fields.Selection(
        selection=[
            ('office_fee', 'رسوم مكتب العمل'),
            ('passport_fee', 'رسوم الجوازات'),
            ('sponsorship_transfer', 'رسوم نقل كفالة'),
        ],
        string='نوع الرسوم', required=True, tracking=True,
    )

    # -- حصة الموظف من الرسوم (قد يدفع جزءاً نقداً/تحويلاً للشركة) --------
    employee_amount = fields.Monetary(
        string='المبلغ الذي يتحمله الموظف', tracking=True,
        help='جزء من إجمالي الرسوم يتحمله الموظف نفسه (يُسدَّد نقداً أو '
             'تحويلاً للشركة) - يُصدَر له عنه فاتورة مستقلة مرتبطة بشريكه '
             'الشخصي، منفصلة تماماً عن فاتورة/قيد الجهة الحكومية.',
    )
    employee_move_id = fields.Many2one(
        'account.move', string='فاتورة الموظف', readonly=True, copy=False,
    )
    employee_payment_state = fields.Selection(
        related='employee_move_id.payment_state', string='حالة سداد الموظف',
        readonly=True,
    )
    recruitment_request_id = fields.Many2one(
        'recruitment.request', string='طلب التوظيف المرتبط',
        readonly=True, copy=False,
        help='إن أُنشئ هذا السجل تلقائياً من طلب توظيف (مرحلة نقل الكفالة) '
             'قبل وجود سجل الموظف الرسمي، يُربَط هنا - ويُكمَل حقل '
             '"اسم الموظف" أعلاه تلقائياً بمجرد إنشاء ذلك السجل لاحقاً.',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('under_review', 'تحت المراجعة'),
            ('confirmed', 'مؤكدة'),
            ('done', 'مسددة'),
            ('cancel', 'ملغاة'),
        ],
        default='draft', tracking=True, copy=False,
    )

    def _sequence_code(self):
        return 'bank.settlement.government.fee'

    def action_done(self):
        """يُكمِّل تنفيذ المسار الأساسي في mixin (قيد الجهة الحكومية)، ثم
        يُصدر فاتورة مستقلة لحصة الموظف إن وُجدت، مرتبطة بشريكه الشخصي -
        فقط للسجلات المُنشأة يدوياً مباشرة من هذا الموديول (بلا طلب توظيف
        مرتبط). السجلات المُنشأة تلقائياً من طلب توظيف (recruitment_request_id
        موجود) تكون حصة الموظف فيها قد سُوِّيت مسبقاً هناك بالكامل - إما
        فاتورة (نقداً) أو سلفة (سجل bank.settlement.advance مستقل) - فلا
        يجوز إصدار فاتورة إضافية هنا حتى لو بقي employee_move_id فارغاً
        عمداً (حالة "سلفة")."""
        super().action_done()
        for rec in self:
            if rec.employee_amount and not rec.employee_move_id and not rec.recruitment_request_id:
                rec.employee_move_id = rec._create_employee_receivable_move()

    def _create_employee_receivable_move(self):
        """ينشئ فاتورة عميل (ذمم مدينة) بحصة الموظف من الرسوم، مرتبطة
        بشريكه الشخصي - نفس الشريك المستخدم أصلاً في recruitment_workflow
        (المرتبط تلقائياً بحساب منصته التحليلي)."""
        self.ensure_one()
        partner = self.employee_id._get_personal_partner()
        if not partner:
            raise UserError(
                'لا يمكن إصدار فاتورة حصة الموظف - لا يوجد شريك (جهة اتصال) '
                'مرتبط بهذا الموظف بعد.'
            )
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': self.transfer_date or fields.Date.context_today(self),
            'ref': self.name,
            'invoice_line_ids': [(0, 0, {
                'name': 'حصة الموظف من الرسوم الحكومية: %s' % self.name,
                'quantity': 1,
                'price_unit': self.employee_amount,
                'analytic_distribution': (
                    {str(self.analytic_account_id.id): 100}
                    if self.analytic_account_id else False
                ),
            })],
        })
        return move.id

    def action_view_employee_move(self):
        self.ensure_one()
        if not self.employee_move_id:
            raise UserError('لا توجد فاتورة موظف مرتبطة بعد.')
        return {
            'name': 'فاتورة حصة الموظف',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.employee_move_id.id,
            'view_mode': 'form',
        }
