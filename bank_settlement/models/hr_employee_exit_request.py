# -*- coding: utf-8 -*-
from odoo import models, _


class HrEmployeeExitRequest(models.Model):
    """توسيع طلب إنهاء الخدمة (المعرَّف في recruitment_workflow) بما يخص
    السداد البنكي وحده - اتجاه الاعتماد يفرض ذلك: bank_settlement يعرف
    recruitment_workflow ولا عكس.

    يضيف:
    1. المعلقات المالية للعرض قبل الاعتماد (سلف ورسوم وتأمين ما زالت
       قيد المعالجة، وجداول دفعات مقدمة لم تنتهِ) - عرض فقط بلا منع
       (قرار صريح): مندوب غادر فعلاً يجب أن يُغلَق ملفه، ومستحقاته
       تُعالَج من تصفيته النهائية.
    2. إيقاف ما تبقّى من جداول "الدفعة المقدمة" عند التنفيذ - وإلا
       استمرت المهمة المجدولة بترحيل مصروف شهري على منصة موظف غادر
       أصلاً (وقد أُغلقت فترة منصته للتو، فيُرحَّل بلا أي توزيع تحليلي).
    """
    _inherit = 'hr.employee.exit.request'

    _PENDING_SETTLEMENT_MODELS = [
        ('bank.settlement.advance', 'سلفة/سلف'),
        ('bank.settlement.government.fee', 'رسوم حكومية'),
        ('bank.settlement.medical.insurance', 'تأمين طبي'),
        ('bank.settlement.vehicle.transfer', 'تحويل مركبة'),
        ('bank.settlement.representative', 'تصفية مندوب'),
    ]

    def _get_exit_pending_items(self):
        items = super()._get_exit_pending_items()
        self.ensure_one()
        if not self.employee_id:
            return items
        for model_name, label in self._PENDING_SETTLEMENT_MODELS:
            Model = self.env[model_name].sudo()
            pending = Model.search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'not in', ('done', 'rejected', 'cancel')),
            ])
            if pending:
                items.append(_(
                    '%(label)s قيد المعالجة: %(count)s سجل بإجمالي %(total)s'
                ) % {
                    'label': label,
                    'count': len(pending),
                    'total': sum(pending.mapped('total_amount')),
                })
        open_lines = self.env['bank.settlement.prepaid.line'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'draft'),
        ])
        if open_lines:
            items.append(_(
                'دفعات مقدمة لم تنتهِ: %(count)s فترة بإجمالي %(total)s '
                '(ستُوقَف تلقائياً عند تنفيذ الخروج)'
            ) % {'count': len(open_lines), 'total': sum(open_lines.mapped('amount'))})
        return items

    def _execute_exit(self):
        res = super()._execute_exit()
        self._stop_prepaid_schedules()
        return res

    def _stop_prepaid_schedules(self):
        """يوقف كل أسطر الاستحقاق التي لم تُرحَّل بعد للموظف الخارج.

        ضروري وليس تحسيناً: فترة منصته أُغلقت للتو ضمن نفس التنفيذ، فأي
        سطر يُرحَّل بعدها لن يجد منصة تغطي تاريخه فيُنشأ قيد مصروف بلا أي
        توزيع تحليلي - أي مصروف يظهر على الشركة بلا منصة، شهراً بعد شهر،
        لموظف غادر."""
        self.ensure_one()
        remaining = self.env['bank.settlement.prepaid.line'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'draft'),
        ])
        if not remaining:
            return remaining
        total = sum(remaining.mapped('amount'))
        remaining.action_cancel_line()
        self.message_post(body=_(
            'أُوقفت %(count)s فترة استحقاق "دفعة مقدمة" لم تُرحَّل بعد '
            '(بإجمالي %(total)s). الرصيد المتبقي في حساب المصروفات '
            'المدفوعة مقدماً يحتاج قيد تسوية يدوياً ضمن التصفية النهائية.'
        ) % {'count': len(remaining), 'total': total})
        return remaining
