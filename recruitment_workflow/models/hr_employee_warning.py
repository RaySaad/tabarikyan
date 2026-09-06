# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# القيم الافتراضية للسياسة - قابلة للتعديل من الإعدادات بلا برمجة
# (انظر res_config_settings.py).
DEFAULT_WARNING_COUNT = 3
DEFAULT_WARNING_VALIDITY_MONTHS = 12


class HrEmployeeWarningType(models.Model):
    """نوع المخالفة الموجِبة للإنذار (تأخر، غياب، سوء تعامل مع عميل،
    مخالفة مرورية متكررة...) - قائمة قابلة للتعديل والإضافة من المستخدم
    نفسه، بدل قائمة ثابتة بالكود لا يقدر أحد غير المطوّر توسيعها."""
    _name = 'hr.employee.warning.type'
    _description = 'نوع المخالفة'
    _order = 'sequence, name'

    name = fields.Char(string='المخالفة', required=True, translate=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    description = fields.Text(string='ملاحظات', translate=True)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)', 'يوجد نوع مخالفة آخر بنفس الاسم بالفعل.',
    )


class HrEmployeeWarning(models.Model):
    """إنذار موظف - مع تصعيد تلقائي (أول/ثانٍ/نهائي) وسقوط تلقائي للإنذارات
    القديمة بعد مدة سريانها.

    مبدآن أساسيان في التصميم:

    1. المستوى لا يختاره أحد يدوياً - يُحسب من عدد الإنذارات *السارية*
       السابقة لنفس الموظف. اختياره يدوياً كان سيسمح بإصدار "إنذار أول"
       لموظف عليه إنذاران بالفعل (خطأ بشري وارد جداً، وله أثر نظامي).

    2. المستوى يُجمَّد لحظة الاعتماد ولا يُعاد حسابه أبداً بعدها: لو بقي
       محسوباً حياً، لتغيّر مستوى إنذار قديم كلما سقط إنذار آخر بالتقادم -
       فيصبح "الإنذار النهائي" الموقَّع من الموظف معروضاً لاحقاً كأنه
       "إنذار أول"، وهو تزوير فعلي لسجل تأديبي.
    """
    _name = 'hr.employee.warning'
    _description = 'إنذار موظف'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='الرقم', required=True, copy=False, readonly=True,
        default=lambda self: _('جديد'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='الموظف', required=True, tracking=True,
        ondelete='restrict', index=True,
    )
    warning_type_id = fields.Many2one(
        'hr.employee.warning.type', string='المخالفة', required=True,
        tracking=True, ondelete='restrict',
    )
    date = fields.Date(
        string='تاريخ المخالفة', required=True, tracking=True,
        default=fields.Date.context_today,
    )
    description = fields.Text(string='تفاصيل المخالفة')
    project_id = fields.Many2one(
        'project.project', string='المنصة', related='employee_id.project_id',
        readonly=True, groups='',
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', default=lambda self: self.env.company,
    )

    # -- التصعيد -----------------------------------------------------------
    level_number = fields.Integer(
        string='ترتيب الإنذار', readonly=True, copy=False, tracking=True,
        help='يُحسب تلقائياً عند الاعتماد من عدد الإنذارات السارية السابقة '
             'لنفس الموظف، ويُجمَّد بعدها فلا يتغيّر مهما سقطت إنذارات أخرى.',
    )
    level_label = fields.Char(
        string='مستوى الإنذار', compute='_compute_level_label', store=True,
    )
    is_final = fields.Boolean(
        string='إنذار نهائي', compute='_compute_level_label', store=True,
    )
    expiry_date = fields.Date(
        string='ساري حتى', readonly=True, copy=False,
        help='بعد هذا التاريخ لا يُحتسب الإنذار في تصعيد الإنذارات '
             'اللاحقة، لكنه يبقى في السجل للتاريخ.',
    )
    is_expired = fields.Boolean(
        string='سقط بالتقادم', compute='_compute_is_expired',
    )

    acknowledgment_file = fields.Binary(string='إشعار موقَّع من الموظف', attachment=True)
    acknowledgment_filename = fields.Char(string='اسم الملف')

    exit_request_id = fields.Many2one(
        'hr.employee.exit.request', string='طلب إنهاء الخدمة', readonly=True,
        copy=False,
        help='يُنشأ تلقائياً كمسودة عند اعتماد الإنذار النهائي - القرار '
             'النهائي يبقى بشرياً ويمر بموافقاته.',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'مسودة'),
            ('confirmed', 'معتمد'),
            ('notified', 'أُبلغ الموظف'),
            ('cancel', 'ملغى'),
        ],
        string='الحالة', default='draft', required=True, tracking=True, copy=False,
    )

    # ------------------------------------------------------------------
    @api.model
    def _get_warning_policy(self):
        """سياسة الإنذارات من الإعدادات (عدد الإنذارات قبل الفصل، ومدة
        سريان الإنذار بالأشهر) - بقيم افتراضية آمنة إن لم تُضبط بعد."""
        params = self.env['ir.config_parameter'].sudo()
        try:
            count = int(params.get_param(
                'recruitment_workflow.warning_count', DEFAULT_WARNING_COUNT))
        except (TypeError, ValueError):
            count = DEFAULT_WARNING_COUNT
        try:
            months = int(params.get_param(
                'recruitment_workflow.warning_validity_months',
                DEFAULT_WARNING_VALIDITY_MONTHS))
        except (TypeError, ValueError):
            months = DEFAULT_WARNING_VALIDITY_MONTHS
        return max(count, 1), max(months, 0)

    @api.depends('level_number')
    def _compute_level_label(self):
        total, _months = self._get_warning_policy()
        ordinals = {1: _('إنذار أول'), 2: _('إنذار ثانٍ'), 3: _('إنذار ثالث')}
        for rec in self:
            number = rec.level_number
            if not number:
                rec.level_label = _('لم يُعتمد بعد')
                rec.is_final = False
                continue
            rec.is_final = number >= total
            if rec.is_final:
                rec.level_label = _('إنذار نهائي (%s)') % number
            else:
                rec.level_label = ordinals.get(number, _('إنذار رقم %s') % number)

    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_expired = bool(rec.expiry_date and rec.expiry_date < today)

    def _count_active_previous_warnings(self):
        """عدد الإنذارات السارية السابقة لنفس الموظف - "سارية" تعني
        معتمدة/مُبلَّغة ولم تسقط بالتقادم *بتاريخ هذا الإنذار* (وليس
        بتاريخ اليوم): إنذار يُسجَّل بأثر رجعي يجب أن يُصعَّد بحسب وضع
        الموظف في تاريخ مخالفته هو، لا في تاريخ إدخاله للنظام."""
        self.ensure_one()
        return self.search_count([
            ('id', '!=', self.id or 0),
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('confirmed', 'notified')),
            '|', ('expiry_date', '=', False), ('expiry_date', '>=', self.date),
            ('date', '<=', self.date),
        ])

    # ------------------------------------------------------------------
    @api.constrains('date')
    def _check_date_not_in_future(self):
        """إنذار بتاريخ مستقبلي يكسر التصعيد نفسه: يُحتسب لاحقاً ضمن
        "الإنذارات السابقة" لإنذار أُصدر قبله فعلياً، فيقفز مستوى موظف
        بمخالفة لم تقع بعد."""
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date and rec.date > today:
                raise UserError(_(
                    'لا يمكن تسجيل إنذار بتاريخ مستقبلي (%s).'
                ) % rec.date)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.employee.warning'
                ) or _('جديد')
            # الشركة من فرع الموظف لا من الفرع النشط في جلسة المُصدِر -
            # وإلا أنشأ مستخدم الفرع الرئيسي إنذاراً "يختفي" عن مسؤولي
            # فرع الموظف نفسه بسبب قاعدة عزل الفروع.
            if vals.get('employee_id') and not vals.get('company_id'):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                if employee.company_id:
                    vals['company_id'] = employee.company_id.id
        return super().create(vals_list)

    def unlink(self):
        # الإنذار سجل تأديبي دائم يُبنى عليه تصعيد لاحق وربما إنهاء خدمة -
        # يُمنع حذفه بعد الاعتماد بنفس مبدأ بقية سجلات النظام. "إلغاء" هو
        # البديل (يُخرجه من التصعيد ويبقيه في السجل).
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'لا يمكن حذف الإنذار "%s" بعد اعتماده - للحفاظ على '
                    'سجل تأديبي كامل. استخدم "إلغاء" بدلاً من ذلك.'
                ) % rec.name)
        return super().unlink()

    def _check_group(self, *group_xmlids):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in group_xmlids):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))

    def action_confirm(self):
        """اعتماد الإنذار - هنا تحديداً يُحسب مستواه ويُجمَّد، وتُحسب مدة
        سريانه، ويُنشأ طلب إنهاء الخدمة تلقائياً إن كان نهائياً."""
        _total, months = self._get_warning_policy()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('يمكن اعتماد الإنذارات في حالة "مسودة" فقط.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_operations',
                'recruitment_workflow.group_recruitment_workflow_hr',
            )
        for rec in self:
            rec.write({
                'state': 'confirmed',
                'level_number': rec._count_active_previous_warnings() + 1,
                'expiry_date': (
                    rec.date + relativedelta(months=months) if months else False
                ),
            })
            rec._create_exit_request_if_final()

    def action_notified(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('يجب اعتماد الإنذار أولاً قبل تسجيل إبلاغ الموظف.'))
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_project_manager',
                'recruitment_workflow.group_recruitment_workflow_hr',
                'recruitment_workflow.group_recruitment_workflow_operations',
                'recruitment_workflow.group_recruitment_workflow_fleet_supervisor',
            )
        self.write({'state': 'notified'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancel':
                continue
            rec._check_group(
                'recruitment_workflow.group_recruitment_workflow_operations',
                'recruitment_workflow.group_recruitment_workflow_hr',
            )
            if rec.exit_request_id and rec.exit_request_id.state == 'done':
                raise UserError(_(
                    'لا يمكن إلغاء هذا الإنذار - نُفِّذ بناءً عليه إنهاء '
                    'خدمة الموظف بالفعل (%s).'
                ) % rec.exit_request_id.name)
        self.write({'state': 'cancel'})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'draft':
                continue
            if rec.exit_request_id:
                raise UserError(_(
                    'لا يمكن إعادة الإنذار لمسودة - مرتبط بطلب إنهاء خدمة '
                    '(%s). ألغِ الطلب أولاً.'
                ) % rec.exit_request_id.name)
            rec._check_group('recruitment_workflow.group_recruitment_workflow_operations')
        self.write({'state': 'draft', 'level_number': 0, 'expiry_date': False})

    def _create_exit_request_if_final(self):
        """عند اعتماد الإنذار النهائي: يُنشأ طلب إنهاء خدمة *كمسودة* فقط
        (قرار صريح) - الفصل قرار بشري له تبعات نظامية، فلا يُنفَّذ آلياً؛
        يمر الطلب بموافقاته المعتادة أو يُلغى."""
        self.ensure_one()
        if not self.is_final or self.exit_request_id:
            return self.env['hr.employee.exit.request']
        existing = self.env['hr.employee.exit.request'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=1)
        if existing:
            # طلب خروج مفتوح بالفعل لنفس الموظف - يُربَط به بدل إنشاء
            # طلب ثانٍ متوازٍ (وهو ممنوع أصلاً، انظر _check_single_open_request).
            self.exit_request_id = existing.id
            existing.message_post(body=_(
                'صدر إنذار نهائي للموظف (%s) وهذا الطلب مفتوح بالفعل.'
            ) % self.name)
            return existing
        request = self.env['hr.employee.exit.request'].create({
            'employee_id': self.employee_id.id,
            'exit_type': 'termination',
            'warning_id': self.id,
            'reason': _('بلوغ الإنذار النهائي: %s') % (self.warning_type_id.name or ''),
        })
        self.exit_request_id = request.id
        self.message_post(body=_(
            'أُنشئ طلب إنهاء خدمة كمسودة (%s) بناءً على الإنذار النهائي - '
            'يحتاج مراجعة واعتماداً بشرياً قبل التنفيذ.'
        ) % request.name)
        return request

    def action_view_exit_request(self):
        self.ensure_one()
        if not self.exit_request_id:
            raise UserError(_('لا يوجد طلب إنهاء خدمة مرتبط بهذا الإنذار.'))
        return {
            'name': _('طلب إنهاء الخدمة'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.exit.request',
            'res_id': self.exit_request_id.id,
            'view_mode': 'form',
        }
