# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # على الشركة لا في ir.config_parameter: نفس موضع
    # work_permit_expiration_notice_period في أودو، وتعدد الشركات هنا
    # ذو معنى فعلي (فرع قد يختلف تنظيمه عن آخر).
    iqama_expiration_notice_period = fields.Integer(
        string='مهلة التنبيه قبل انتهاء الإقامة (بالأيام)', default=60,
        help='قبل هذه المدة من تاريخ انتهاء إقامة المندوب يُنشأ نشاط '
             'لمسؤول الموارد البشرية للتنبيه بالتجديد. صفر = بلا تنبيه.',
    )

    # شركة الأسطول: الشركة المالكة للمركبات التي تستعملها بقية الفروع.
    # مُعرَّفة هنا لا في موديول الأجرة، لأن القيود والشاشات في سير
    # التوظيف نفسه تحتاج معرفتها لتسمح بمركبة الأسطول لموظفي الفروع.
    is_fleet_owner = fields.Boolean(
        string='شركة الأسطول',
        help='الشركة المالكة للمركبات التي تؤجّرها لفروع التشغيل. '
             'مركباتها متاحة لمناديب كل الفروع.',
    )

    @api.constrains('is_fleet_owner')
    def _check_single_fleet_owner(self):
        """شركتا أسطول تعنيان قائمتَي مركبات متاحة متوازيتين."""
        for company in self.filtered('is_fleet_owner'):
            other = self.sudo().search([
                ('is_fleet_owner', '=', True), ('id', '!=', company.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    'شركة الأسطول محدَّدة مسبقاً: "%s". ألغِ تحديدها أولاً.'
                ) % other.display_name)

    @api.model
    def _get_fleet_owner_company(self):
        return self.sudo().search([('is_fleet_owner', '=', True)], limit=1)
