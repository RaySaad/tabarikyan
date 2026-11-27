# -*- coding: utf-8 -*-
"""ربط مندوب التوصيل بملف الموظف وبمركبة الأسطول.

المندوب كيان مستقل عمداً (لا رخصة أودو له، ولا دخول إلى /web). لكن
كثيراً منهم موظفون عندك فعلاً، ولهم مركبات في الأسطول - والفصل التام
يعني إدخال الاسم والجوال مرتين، وصيانةً لمركبة لا تعرف من يقودها.

هذا الجسر يربط بلا أن يدمج: المندوب يبقى كياناً مستقلاً، ويُشير إلى
موظف ومركبة إن وُجدا.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class QuickDeliveryDriver(models.Model):
    _inherit = 'quick.delivery.driver'

    employee_id = fields.Many2one(
        'hr.employee', string='ملف الموظف', ondelete='set null', index=True,
        help='يربط المندوب بموظفه. لا يُغني عنه: مندوب متعاون بلا ملف '
             'يبقى مندوباً.')
    employee_department_id = fields.Many2one(
        related='employee_id.department_id', string='القسم', readonly=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='مركبة الأسطول', ondelete='set null',
        index=True,
        help='مركبة من الأسطول. تُغني عن كتابة اللوحة يدوياً، وتربط '
             'الصيانة والوقود بمن يقودها.')

    _employee_uniq = models.Constraint(
        'unique(employee_id)',
        'هذا الموظف مرتبط بمندوب آخر بالفعل.',
    )

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """يملأ ما يُدخَل مرتين عادةً - ولا يمسّ ما كُتب."""
        for rec in self:
            employee = rec.employee_id
            if not employee:
                continue
            if not rec.name or rec.name == _('مندوب جديد'):
                rec.name = employee.name
            if not rec.phone:
                rec.phone = (employee.mobile_phone or employee.work_phone
                             or '')

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        for rec in self:
            if rec.vehicle_id and not rec.vehicle_plate:
                rec.vehicle_plate = rec.vehicle_id.license_plate

    @api.constrains('employee_id', 'active')
    def _check_employee_active(self):
        """يمنع ربط مندوب عامل بموظف أُنهيت خدمته - عند الربط وحده.

        والقيد وحده لا يكفي: أرشفة الموظف من بطاقته لا تمرّ على
        المندوب، فالحارس الحقيقي في موضعين آخرين - منع الإسناد، وإيقاف
        المندوب عند الأرشفة.
        """
        for rec in self:
            if rec.active and rec.employee_id \
                    and not rec.employee_id.active:
                raise ValidationError(_(
                    'الموظف "%s" مؤرشف (أُنهيت خدمته). أوقف المندوب أو '
                    'اربطه بموظف آخر.') % rec.employee_id.name)

    def _qd_lock_if_free(self):
        """لا إسناد لمندوب موظفه أُنهيت خدمته.

        هذا هو الحارس الذي يمنع الضرر فعلاً: رجلٌ تُنهى خدمته صباحاً
        ويبقى في التطبيق يستلم طلبات العملاء وأموالهم ظهراً.
        """
        self.ensure_one()
        employee = self.sudo().employee_id
        if employee and not employee.active:
            _logger.warning(
                'تخطّي المندوب %s في الإسناد: موظفه %s مؤرشف.',
                self.name, employee.name)
            return False
        return super()._qd_lock_if_free()

    def action_open_employee(self):
        self.ensure_one()
        if not self.employee_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'res_id': self.employee_id.id,
            'view_mode': 'form',
        }

    def action_open_vehicle(self):
        self.ensure_one()
        if not self.vehicle_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.vehicle',
            'res_id': self.vehicle_id.id,
            'view_mode': 'form',
        }


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def write(self, vals):
        res = super().write(vals)
        # إنهاء الخدمة يُوقف المندوب في اللحظة نفسها: الاعتماد على أن
        # يتذكّر أحدهم إيقافه يدوياً يعني رجلاً خارج الخدمة ومعه عهدة
        # تحصيل في جيبه.
        if vals.get('active') is False:
            drivers = self.env['quick.delivery.driver'].sudo().search(
                [('employee_id', 'in', self.ids)])
            for driver in drivers:
                if driver._qd_has_open_order():
                    _logger.warning(
                        'الموظف %s أُرشف ومندوبه %s عليه طلب حيّ - لم '
                        'يُوقف تلقائياً، راجعه يدوياً.',
                        driver.employee_id.name, driver.name)
                    continue
                driver.write({'driver_status': 'offline', 'active': False})
                driver._qd_close_session()
                _logger.info('أُوقف المندوب %s لأرشفة موظفه.', driver.name)
        return res

    qd_driver_id = fields.Many2one(
        'quick.delivery.driver', string='مندوب التوصيل',
        compute='_compute_qd_driver_id', search='_search_qd_driver_id')
    qd_is_driver = fields.Boolean(
        string='مندوب توصيل فوري', compute='_compute_qd_driver_id')

    def _compute_qd_driver_id(self):
        Driver = self.env['quick.delivery.driver'].sudo()
        drivers = Driver.with_context(active_test=False).search(
            [('employee_id', 'in', self.ids)])
        by_employee = {driver.employee_id.id: driver for driver in drivers}
        for rec in self:
            driver = by_employee.get(rec.id)
            rec.qd_driver_id = driver.id if driver else False
            rec.qd_is_driver = bool(driver)

    def _search_qd_driver_id(self, operator, value):
        if operator in ('in', 'not in') and isinstance(value, bool) is False:
            return [('id', 'in', self.env['quick.delivery.driver'].sudo()
                     .search([('id', operator, value)])
                     .mapped('employee_id').ids)]
        raise NotImplementedError(operator)

    def action_open_qd_driver(self):
        self.ensure_one()
        if not self.qd_driver_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'quick.delivery.driver',
            'res_id': self.qd_driver_id.id,
            'view_mode': 'form',
        }


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    qd_driver_ids = fields.One2many(
        'quick.delivery.driver', 'vehicle_id', string='مندوبو التوصيل')
    qd_driver_count = fields.Integer(string='عدد المندوبين',
                                     compute='_compute_qd_driver_count')

    def _compute_qd_driver_count(self):
        groups = self.env['quick.delivery.driver'].sudo()._read_group(
            [('vehicle_id', 'in', self.ids)],
            groupby=['vehicle_id'], aggregates=['__count'])
        counts = {vehicle.id: count for vehicle, count in groups}
        for rec in self:
            rec.qd_driver_count = counts.get(rec.id, 0)
