# -*- coding: utf-8 -*-
from odoo import models, fields

from .hr_employee_warning import (
    DEFAULT_WARNING_COUNT,
    DEFAULT_WARNING_VALIDITY_MONTHS,
)


class ResConfigSettings(models.TransientModel):
    """سياسة الإنذارات قابلة للتعديل من الإعدادات بلا برمجة - عدد
    الإنذارات قبل بلوغ "النهائي"، ومدة سريان الإنذار قبل سقوطه
    بالتقادم. القيمتان تؤثران على *الإنذارات الجديدة فقط*: مستوى كل
    إنذار وتاريخ سريانه يُجمَّدان لحظة اعتماده (انظر
    hr_employee_warning.action_confirm) فلا يتغيّر سجل تأديبي قديم
    بمجرد تعديل السياسة لاحقاً."""
    _inherit = 'res.config.settings'

    recruitment_warning_count = fields.Integer(
        string='عدد الإنذارات قبل الفصل',
        default=DEFAULT_WARNING_COUNT,
        config_parameter='recruitment_workflow.warning_count',
        help='عند بلوغ هذا الرقم يُعتبر الإنذار "نهائياً" ويُنشأ طلب '
             'إنهاء خدمة كمسودة تلقائياً.',
    )
    recruitment_warning_validity_months = fields.Integer(
        string='مدة سريان الإنذار (بالأشهر)',
        default=DEFAULT_WARNING_VALIDITY_MONTHS,
        config_parameter='recruitment_workflow.warning_validity_months',
        help='بعد انقضائها لا يُحتسب الإنذار في تصعيد الإنذارات اللاحقة، '
             'لكنه يبقى في السجل للتاريخ. صفر = لا يسقط أبداً.',
    )
