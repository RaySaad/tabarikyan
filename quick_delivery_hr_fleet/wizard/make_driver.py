# -*- coding: utf-8 -*-
"""تحويل موظفين إلى مندوبين دفعةً واحدة.

المنطق المعتاد كان معكوساً: تُنشئ المندوب يدوياً ثم تربطه بموظف،
فتكتب الاسم والجوال مرتين لعشرين رجلاً. هنا تفتح قائمة الموظفين،
تحدّد من تشاء، وتختار لأي شركة يعملون.
"""
import logging
import secrets

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QuickDeliveryMakeDriver(models.TransientModel):
    _name = 'quick.delivery.make.driver'
    _description = 'تحويل موظفين إلى مندوبين'

    # المعالج قد يحمل أرقاماً سرية مولَّدة. السجلات العابرة تبقى حتى
    # تُكنس، فنُقصّر عمرها إلى ست دقائق: ورقة فيها عشرون رقماً سرياً
    # لا تبقى في قاعدة البيانات ساعةً كاملة.
    _transient_max_hours = 0.1

    employee_ids = fields.Many2many(
        'hr.employee', string='الموظفون', required=True)
    client_ids = fields.Many2many(
        'res.partner', string='يخدمون هذه الشركات',
        domain=[('is_qcommerce_client', '=', True)],
        help='اتركه فارغاً ليخدموا كل الشركات.')
    commission_per_order = fields.Float(
        string='عمولة الطلب (SAR)', default=8.0)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='مركبة واحدة للجميع',
        help='تُربط بكل من يُنشأ. اتركها فارغة وحدّد لكلٍّ مركبته '
             'لاحقاً.')
    generate_pins = fields.Boolean(
        string='ولّد الأرقام السرية الآن', default=False,
        help='تُعرض مرة واحدة بعد الإنشاء ثم لا تُقرأ.\n'
             'الأسلم تركه مطفأً وتوليد رمز كلٍّ عند تسليمه جواله - '
             'ورقةٌ فيها أرقام عشرين مندوباً خطرٌ بذاتها.')

    result_text = fields.Text(string='النتيجة', readonly=True)
    created_count = fields.Integer(string='أُنشئ', readonly=True)
    skipped_text = fields.Text(string='تُخطّي', readonly=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') == 'hr.employee' \
                and active_ids:
            values['employee_ids'] = [(6, 0, active_ids)]
        return values

    # ------------------------------------------------------------------
    def action_create_drivers(self):
        self.ensure_one()
        Driver = self.env['quick.delivery.driver']
        created = []
        skipped = []

        # قراءة المؤرشفين أيضاً: حقل many2many يُرشّحهم عند القراءة،
        # فكان الموظف المؤرشف يختفي من الاختيار صامتاً - لا يُنشأ ولا
        # يُقال لماذا، فيبحث المستخدم عن مندوب لم يُطلب إنشاؤه أصلاً.
        employees = self.with_context(active_test=False).employee_ids
        for employee in employees:
            problem = self._qd_reject_reason(employee, Driver)
            if problem:
                skipped.append('%s — %s' % (employee.name, problem))
                continue

            phone = (employee.mobile_phone or employee.work_phone or '').strip()
            vals = {
                'name': employee.name,
                'phone': phone,
                'employee_id': employee.id,
                'commission_per_order': self.commission_per_order,
                'client_ids': [(6, 0, self.client_ids.ids)],
            }
            if self.vehicle_id:
                vals['vehicle_id'] = self.vehicle_id.id
                vals['vehicle_plate'] = self.vehicle_id.license_plate
            driver = Driver.create(vals)

            pin = ''
            if self.generate_pins:
                pin = '%06d' % secrets.randbelow(1000000)
                driver.pin = pin
            created.append((driver, pin))

        if not created and skipped:
            raise UserError(_('لم يُنشأ أحد:\n%s') % '\n'.join(skipped))

        _logger.info('أُنشئ %d مندوباً من قائمة الموظفين (تُخطّي %d).',
                     len(created), len(skipped))
        return self._qd_result_action(created, skipped)

    def _qd_reject_reason(self, employee, Driver):
        """لماذا لا يصلح هذا الموظف مندوباً - برسالة تُقرأ لا بصمت."""
        if not employee.active:
            return _('مؤرشف (أُنهيت خدمته)')
        phone = (employee.mobile_phone or employee.work_phone or '').strip()
        if len(Driver._phone_key(phone)) < 9:
            return _('بلا جوال صالح في ملفه')
        existing = Driver.with_context(active_test=False).search(
            [('employee_id', '=', employee.id)], limit=1)
        if existing:
            return _('مندوب بالفعل (%s)') % existing.name
        same_phone = Driver.with_context(active_test=False).search(
            [('login_key', '=', Driver._phone_key(phone))], limit=1)
        if same_phone:
            return _('جواله مسجَّل لمندوب آخر (%s)') % same_phone.name
        return ''

    def _qd_result_action(self, created, skipped):
        lines = []
        for driver, pin in created:
            if pin:
                lines.append('%-22s %-14s %s' % (driver.name, driver.phone,
                                                 pin))
            else:
                lines.append('%-22s %s' % (driver.name, driver.phone))
        header = (_('الاسم | الجوال | رمز الدخول') if self.generate_pins
                  else _('الاسم | الجوال'))
        note = _('\n\nالأرقام السرية أعلاه تُعرض مرة واحدة. انسخها الآن '
                 '- المخزَّن بصمتها لا نصّها، وهذه الشاشة تُمحى خلال '
                 'دقائق.') if self.generate_pins else _(
                 '\n\nلم تُولَّد أرقام سرية. ولّد رمز كلٍّ من بطاقته عند '
                 'تسليمه جواله.')

        self.write({
            'created_count': len(created),
            'result_text': '%s\n%s%s' % (header, '\n'.join(lines), note),
            'skipped_text': '\n'.join(skipped),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'quick_delivery_hr_fleet.view_make_driver_result').id,
            'target': 'new',
            'context': self.env.context,
        }

    def action_open_drivers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('المندوبون'),
            'res_model': 'quick.delivery.driver',
            'view_mode': 'list,form',
            'domain': [('employee_id', 'in', self.employee_ids.ids)],
        }
