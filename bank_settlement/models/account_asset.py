# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountAssetAsset(models.Model):
    """تمديد على om_account_asset (لا نلمس ملفاته) - يضيف فقط ربط "الأصل"
    (جدول الاستهلاك) بالموظف/المندوب الذي يخصه، حتى تستطيع دالة
    _prepare_move (في account.asset.depreciation.line أدناه) معرفة
    منصته الفعلية عند كل قيد دوري."""
    _inherit = 'account.asset.asset'

    employee_id = fields.Many2one(
        'hr.employee', string='المندوب', tracking=True,
        help='إن كان هذا "الأصل" ناتجاً عن دفعة مقدمة في السداد البنكي '
             'تخص مندوباً محدداً - يُستخدَم لتحديد التوزيع التحليلي '
             'الصحيح تلقائياً لكل قيد دوري حسب منصته الفعلية في تاريخه، '
             'بدل توزيع ثابت واحد طوال الجدول.',
    )


class AccountAssetDepreciationLine(models.Model):
    """تمديد على om_account_asset - يضيف:
    1) تاريخ بداية كل فترة استهلاك (الجدول الأصلي يخزّن فقط تاريخ
       نهايتها في depreciation_date) - ضروري لحساب النسبة الفعلية
       المنقضية عند تسوية نقل منصة منتصف الفترة (انظر
       hr_employee._settle_prepaid_lines_on_transfer).
    2) تجاوز _prepare_move (هنا فعلياً، وليس في account.asset.asset -
       الدالة الأصلية مُعرَّفة على هذا النموذج تحديداً) ليستبدل التوزيع
       التحليلي الثابت (المخزَّن على الأصل نفسه) بتوزيع مُحسَب ديناميكياً
       وقت إنشاء *هذا القيد تحديداً* من منصة الموظف الفعلية في تاريخ هذا
       السطر - جوهر الحل: بما أن كل قيد دوري يُنشأ فعلياً فقط عند
       استحقاقه (عبر cron om_account_asset الشهري القياسي، بلا أي
       تعديل عليه)، فإن أي نقل منصة سابق لتاريخ القيد يُقرأ صحيحاً هنا
       تلقائياً - لا حاجة لتعديل القيود المستقبلية يدوياً عند حدوث نقل."""
    _inherit = 'account.asset.depreciation.line'

    period_start_date = fields.Date(string='بداية فترة هذا السطر')

    def _prepare_move(self, line):
        move_vals = super()._prepare_move(line)
        employee = line.asset_id.employee_id
        if employee:
            distribution = employee._get_platform_analytic_distribution(line.depreciation_date)
            for command in move_vals.get('line_ids', []):
                # عنصر (0, 0, vals) - command[2] هو قاموس قيم سطر القيد
                if len(command) == 3 and isinstance(command[2], dict):
                    command[2]['analytic_distribution'] = distribution
        return move_vals
