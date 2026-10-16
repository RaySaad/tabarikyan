# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FleetFuelLog(models.Model):
    """تعبئة وقود: السجل على المركبة، والتكلفة على الفرع المستأجر.

    الوقود يدفعه المستأجر لا الأسطول - فلا يصح أن يدخل تكلفة شركة
    الأسطول ولا يُخصم من ربحيتها. لكنه **يجب** أن يُسجَّل على المركبة:
    بلا ذلك لا يُعرف استهلاكها (كم/لتر) ولا يُكشف تسريب أو استهلاك
    غير مشروع، ويضعف أيضاً منطق الصيانة بالكيلومترات لأنه يفقد
    قراءات العدّاد المنتظمة.

    الفرع يُشتق من **عقد التأجير الساري يوم التعبئة** لا من شركة من
    يُدخل السجل - فلو نُقلت السيارة لفرع آخر بعدها بقيت تعبئات الماضي
    منسوبة لصاحبها الحقيقي.
    """
    _name = 'fleet.fuel.log'
    _description = 'تعبئة وقود'
    _order = 'date desc, odometer desc, id desc'
    _rec_name = 'vehicle_id'

    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة', required=True, ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='التاريخ', required=True, default=fields.Date.context_today,
        index=True,
    )
    liters = fields.Float(string='اللترات', required=True)
    price_per_liter = fields.Float(
        string='سعر اللتر', compute='_compute_price_per_liter', store=True)
    amount = fields.Monetary(string='المبلغ', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='العملة',
        default=lambda self: self.env.company.currency_id, required=True)
    odometer = fields.Float(string='قراءة العدّاد', required=True)

    # الفرع المتحمِّل - يُشتق من العقد لا من مُدخل السجل.
    company_id = fields.Many2one(
        'res.company', string='الفرع المتحمِّل', required=True, index=True,
        compute='_compute_company_id', store=True, readonly=False,
        # precompute: الحقول المحسوبة المخزَّنة تُحسب بعد الإدراج افتراضياً،
        # وهذا العمود إلزامي - فبلا الحساب المسبق يفشل الإنشاء.
        precompute=True,
        help='الفرع الذي كانت المركبة لديه يوم التعبئة - تكلفة الوقود '
             'عليه، ولا تدخل دفاتر شركة الأسطول.',
    )
    contract_id = fields.Many2one(
        'fleet.rental.contract', string='العقد', readonly=True,
        compute='_compute_company_id', store=True, precompute=True,
    )
    # ليس محسوباً: يُملأ من العقد عند الإنشاء ويبقى قابلاً للتعديل -
    # وقراءته داخل دالة حساب تضمّه تُنتج اعتماداً دائرياً.
    driver_id = fields.Many2one('hr.employee', string='السائق')
    settlement_id = fields.Many2one(
        'bank.settlement.vehicle.transfer', string='سجل السداد',
        help='سجل صرف الوقود في السداد البنكي إن وُجد - الربط للتتبّع '
             'فقط، فالمال يُصرف هناك لا هنا.',
    )

    # -- الاستهلاك ------------------------------------------------------
    distance = fields.Float(
        string='المسافة منذ التعبئة السابقة', compute='_compute_consumption',
        store=True,
    )
    consumption = fields.Float(
        string='كم/لتر', compute='_compute_consumption', store=True,
        help='المسافة منذ التعبئة السابقة مقسومة على لترات هذه التعبئة. '
             'انخفاضها المفاجئ مؤشر تسريب أو استهلاك غير مشروع.',
    )
    note = fields.Char(string='ملاحظة')

    @api.depends('liters', 'amount')
    def _compute_price_per_liter(self):
        for log in self:
            log.price_per_liter = (log.amount / log.liters) if log.liters else 0.0

    def _contract_at(self, vehicle, day):
        """العقد الساري على المركبة في ذلك اليوم - هو من يحدد المتحمِّل."""
        if not vehicle or not day:
            return self.env['fleet.rental.contract']
        return self.env['fleet.rental.contract'].sudo().search([
            ('vehicle_id', '=', vehicle.id),
            ('date_start', '<=', day),
            '|', ('date_end', '=', False), ('date_end', '>', day),
            ('state', 'in', ('active', 'ended')),
        ], order='date_start desc', limit=1)

    @api.depends('vehicle_id', 'date')
    def _compute_company_id(self):
        for log in self:
            contract = log._contract_at(log.vehicle_id, log.date)
            log.contract_id = contract
            # بلا عقد: المركبة كانت لدى الأسطول نفسه، فالتكلفة عليه.
            log.company_id = (contract.company_id or log.vehicle_id.company_id
                              or self.env.company)

    @api.depends('vehicle_id', 'odometer', 'liters', 'date')
    def _compute_consumption(self):
        for log in self:
            previous = self.sudo().search([
                ('vehicle_id', '=', log.vehicle_id.id),
                ('id', '!=', log.id or 0),
                '|', ('date', '<', log.date),
                '&', ('date', '=', log.date), ('odometer', '<', log.odometer),
            ], order='date desc, odometer desc', limit=1) if log.vehicle_id else False
            distance = (log.odometer - previous.odometer) if previous else 0.0
            log.distance = distance if distance > 0 else 0.0
            log.consumption = (log.distance / log.liters) if (log.liters and log.distance) else 0.0

    @api.constrains('odometer', 'vehicle_id', 'date')
    def _check_odometer(self):
        """قراءة أقل من تعبئة سابقة تُفسد كل حسابات الاستهلاك والصيانة."""
        for log in self:
            previous = self.sudo().search([
                ('vehicle_id', '=', log.vehicle_id.id),
                ('id', '!=', log.id),
                ('date', '<=', log.date),
            ], order='date desc, odometer desc', limit=1)
            if previous and log.odometer < previous.odometer:
                raise ValidationError(_(
                    'قراءة العدّاد (%(now)s) أقل من قراءة تعبئة سابقة '
                    '(%(prev)s بتاريخ %(date)s).'
                ) % {'now': log.odometer, 'prev': previous.odometer,
                     'date': previous.date})

    @api.constrains('liters', 'amount')
    def _check_positive(self):
        for log in self:
            if log.liters <= 0 or log.amount <= 0:
                raise ValidationError(_('اللترات والمبلغ يجب أن يكونا أكبر من صفر.'))

    @api.model_create_multi
    def create(self, vals_list):
        logs = super().create(vals_list)
        for log in logs:
            if not log.driver_id and log.contract_id.employee_id:
                log.driver_id = log.contract_id.employee_id
        # قراءة العدّاد تُفيد الصيانة بالكيلومترات أيضاً - فنكتبها على
        # المركبة بدل أن تبقى حبيسة سجل الوقود.
        for log in logs:
            log._push_odometer()
        return logs

    def write(self, vals):
        res = super().write(vals)
        if 'odometer' in vals or 'date' in vals:
            self._push_odometer()
        return res

    def _push_odometer(self):
        for log in self:
            if log.odometer and log.odometer > (log.vehicle_id.odometer or 0.0):
                self.env['fleet.vehicle.odometer'].sudo().create({
                    'vehicle_id': log.vehicle_id.id,
                    'value': log.odometer,
                    'date': log.date,
                })
