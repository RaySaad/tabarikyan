# -*- coding: utf-8 -*-
from odoo import models, fields


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
