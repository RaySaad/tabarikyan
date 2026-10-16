# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetMaintenancePlan(models.Model):
    """خطة صيانة دورية بالمسافة أو بالزمن - أو بهما معاً.

    أودو تجدول الصيانة الوقائية **بالأيام فقط**، وفي أسطول توصيل
    المعيار الحقيقي هو الكيلومترات: سيارة تمشي 6000 كم شهرياً لا
    تُقاس بسيارة تمشي 800. هذه الخطة تحسب الاستحقاق من الاثنين معاً
    وتأخذ أيهما يسبق.

    والتنبيه **مبكر** لا لحظة الاستحقاق: قبل مسافة محدَّدة (500 كم
    افتراضاً) أو مدة محدَّدة (3 أيام) - فيُحجَز موعد الورشة قبل أن
    تتجاوز المركبة موعدها وهي تعمل.
    """
    _name = 'fleet.maintenance.plan'
    _description = 'خطة صيانة دورية'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state desc, next_due_date, id'

    name = fields.Char(
        string='الخطة', compute='_compute_name', store=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='المركبة', required=True, tracking=True,
        ondelete='cascade',
    )
    service_type_id = fields.Many2one(
        'fleet.service.type', string='نوع الصيانة', required=True, tracking=True,
        ondelete='restrict',
    )
    company_id = fields.Many2one(
        related='vehicle_id.company_id', store=True, readonly=True)
    active = fields.Boolean(default=True)

    # -- الفواصل --------------------------------------------------------
    interval_km = fields.Integer(
        string='كل (كم)', tracking=True,
        help='صفر = لا تُجدوَل بالمسافة.',
    )
    interval_days = fields.Integer(
        string='كل (يوم)', tracking=True,
        help='صفر = لا تُجدوَل بالزمن.',
    )
    warning_km = fields.Integer(
        string='تنبيه قبل (كم)', default=500,
        help='يبدأ التنبيه قبل هذه المسافة من الاستحقاق.',
    )
    warning_days = fields.Integer(
        string='تنبيه قبل (يوم)', default=3)

    # -- آخر تنفيذ ------------------------------------------------------
    last_service_date = fields.Date(string='آخر صيانة', tracking=True)
    last_service_odometer = fields.Float(
        string='عداد آخر صيانة', tracking=True)
    service_count = fields.Integer(
        string='مرات التنفيذ', readonly=True, copy=False)

    # -- الاستحقاق ------------------------------------------------------
    current_odometer = fields.Float(
        string='العداد الحالي', compute='_compute_due', store=True)
    next_due_date = fields.Date(
        string='الاستحقاق (تاريخ)', compute='_compute_due', store=True)
    next_due_odometer = fields.Float(
        string='الاستحقاق (عداد)', compute='_compute_due', store=True)
    remaining_days = fields.Integer(
        string='المتبقي (يوم)', compute='_compute_due', store=True)
    remaining_km = fields.Float(
        string='المتبقي (كم)', compute='_compute_due', store=True)
    state = fields.Selection(
        selection=[
            ('ok', 'ضمن المدة'),
            ('warning', 'اقترب الاستحقاق'),
            ('overdue', 'متأخرة'),
            ('unplanned', 'بلا جدولة'),
        ],
        string='الحالة', compute='_compute_due', store=True, tracking=True,
    )
    note = fields.Text(string='ملاحظات')

    # فهرس فريد جزئي لا قيد عادي، ولسببين:
    # ١) _sql_constraints لم تعد مدعومة في أودو 19 - الصيغة المعتمدة
    #    models.Constraint/UniqueIndex (نبّه سجل الخادم على ذلك).
    # ٢) التفرّد يجب أن يسري على الخطط **الفعّالة** وحدها: قيد يشمل
    #    active كعمود عادي كان سيمنع أرشفة خطتين بنفس النوع للمركبة
    #    نفسها، وهو منع بلا معنى.
    _unique_active_plan = models.UniqueIndex(
        '(vehicle_id, service_type_id) WHERE (active IS TRUE)',
        'توجد خطة فعّالة بنفس نوع الصيانة لهذه المركبة.',
    )

    @api.depends('vehicle_id', 'service_type_id')
    def _compute_name(self):
        for plan in self:
            plan.name = '%s - %s' % (
                plan.vehicle_id.display_name or '', plan.service_type_id.name or '')

    @api.depends('vehicle_id', 'vehicle_id.odometer', 'interval_km', 'interval_days',
                 'warning_km', 'warning_days',
                 'last_service_date', 'last_service_odometer')
    def _compute_due(self):
        today = fields.Date.context_today(self)
        for plan in self:
            odometer = plan.vehicle_id.odometer or 0.0
            plan.current_odometer = odometer

            start_date = plan.last_service_date
            plan.next_due_date = (
                start_date + timedelta(days=plan.interval_days)
                if plan.interval_days and start_date else False)
            plan.next_due_odometer = (
                plan.last_service_odometer + plan.interval_km
                if plan.interval_km else 0.0)

            plan.remaining_days = (
                (plan.next_due_date - today).days if plan.next_due_date else 0)
            plan.remaining_km = (
                plan.next_due_odometer - odometer if plan.next_due_odometer else 0.0)

            plan.state = plan._evaluate_state()

    def _evaluate_state(self):
        """أيهما يسبق يحكم: المسافة أو الزمن."""
        self.ensure_one()
        by_km = bool(self.interval_km)
        by_date = bool(self.interval_days and self.next_due_date)
        if not by_km and not by_date:
            return 'unplanned'
        # بلا تنفيذ سابق لا استحقاق محسوب - الخطة تنتظر أول صيانة.
        if not self.last_service_date and not self.last_service_odometer:
            return 'unplanned'
        if (by_km and self.remaining_km <= 0) or (by_date and self.remaining_days < 0):
            return 'overdue'
        if (by_km and self.remaining_km <= self.warning_km) or \
                (by_date and self.remaining_days <= self.warning_days):
            return 'warning'
        return 'ok'

    # ------------------------------------------------------------------
    def action_register_service(self):
        """تسجيل تنفيذ الصيانة - يفتح معالجاً يكتب سجل الخدمة ويعيد
        جدولة الدورة التالية تلقائياً."""
        self.ensure_one()
        return {
            'name': _('تسجيل تنفيذ الصيانة'),
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.maintenance.execute.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def _register_execution(self, date, odometer, amount=0.0, note=False):
        """يُحدِّث الخطة بعد تنفيذ صيانة - فتبدأ الدورة التالية من هنا."""
        self.ensure_one()
        log = self.env['fleet.vehicle.log.services'].sudo().create({
            'vehicle_id': self.vehicle_id.id,
            'service_type_id': self.service_type_id.id,
            'date': date,
            'amount': amount,
            'odometer': odometer,
            'description': note or self.name,
        })
        self.write({
            'last_service_date': date,
            'last_service_odometer': odometer,
            'service_count': self.service_count + 1,
        })
        # نشاط التنبيه السابق لم يعد ذا معنى بعد التنفيذ.
        self.activity_ids.action_feedback(feedback=_('نُفِّذت الصيانة'))
        self.message_post(body=_(
            'نُفِّذت الصيانة في %(date)s عند عداد %(odo)s. الاستحقاق التالي: '
            '%(next)s'
        ) % {'date': date, 'odo': odometer,
             'next': self.next_due_odometer or self.next_due_date or '-'})
        return log

    # ------------------------------------------------------------------
    def _notify_due(self):
        """نشاط لمسؤول الأسطول عن كل خطة قاربت أو تجاوزت استحقاقها -
        مرة واحدة لكل دورة: وجود نشاط مفتوح يمنع التكرار اليومي."""
        for plan in self:
            if plan.state not in ('warning', 'overdue'):
                continue
            if plan.activity_ids:
                continue
            user = plan.vehicle_id.manager_id or plan.env.user
            reason = []
            if plan.interval_km and plan.remaining_km <= plan.warning_km:
                reason.append(_('متبقٍ %s كم') % int(plan.remaining_km))
            if plan.interval_days and plan.next_due_date and \
                    plan.remaining_days <= plan.warning_days:
                reason.append(_('متبقٍ %s يوماً') % plan.remaining_days)
            plan.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('صيانة %(type)s - %(vehicle)s') % {
                    'type': plan.service_type_id.name,
                    'vehicle': plan.vehicle_id.display_name},
                note=' - '.join(reason) or _('اقترب موعد الصيانة'),
                user_id=user.id,
            )

    @api.model
    def _cron_check_due(self):
        """تعمل يومياً: تعيد تقييم الخطط وتنبّه عن المستحق.

        إعادة التقييم ضرورية لأن الحالة تعتمد على تاريخ اليوم وعلى
        عداد المركبة - وكلاهما يتغير بلا تعديل على الخطة نفسها."""
        plans = self.sudo().search([])
        plans._compute_due()
        plans.flush_recordset()
        due = plans.filtered(lambda p: p.state in ('warning', 'overdue'))
        due._notify_due()
        return len(due)


class FleetMaintenanceExecuteWizard(models.TransientModel):
    _name = 'fleet.maintenance.execute.wizard'
    _description = 'تسجيل تنفيذ صيانة'

    plan_id = fields.Many2one(
        'fleet.maintenance.plan', string='الخطة', required=True, readonly=True)
    vehicle_id = fields.Many2one(
        related='plan_id.vehicle_id', readonly=True)
    date = fields.Date(
        string='تاريخ التنفيذ', required=True,
        default=fields.Date.context_today)
    odometer = fields.Float(
        string='قراءة العداد', required=True,
        default=lambda self: self._default_odometer())
    amount = fields.Monetary(string='التكلفة')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    note = fields.Char(string='ملاحظة')

    @api.model
    def _default_odometer(self):
        plan = self.env['fleet.maintenance.plan'].browse(
            self.env.context.get('default_plan_id'))
        return plan.vehicle_id.odometer if plan else 0.0

    def action_confirm(self):
        self.ensure_one()
        if self.odometer < self.plan_id.last_service_odometer:
            raise UserError(_(
                'قراءة العداد (%(now)s) أقل من قراءة آخر صيانة (%(last)s).'
            ) % {'now': self.odometer, 'last': self.plan_id.last_service_odometer})
        self.plan_id._register_execution(
            self.date, self.odometer, self.amount, self.note)
        return {'type': 'ir.actions.act_window_close'}
