# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # نفس حماية recruitment_workflow.hr_employee.unlink() بالضبط، لكن هنا
    # لنماذج bank_settlement تحديداً (سلفة/رسوم حكومية/تأمين طبي/تحويل
    # مركبة/تصفية مندوب) - موديول منفصل لا يعرفه recruitment_workflow،
    # فلا بد من فحص مستقل. سبّب غياب هذا الفحص فقدان بيانات فعلياً: حُذف
    # موظف له سلفة "بانتظار الموافقة" فتعطّلت الشاشة تماماً (الحقل إلزامي
    # في الواجهة لكن غير قابل للتعديل بعد مغادرة "مسودة").
    _BANK_SETTLEMENT_MODELS = [
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.medical.insurance',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.representative',
    ]

    def unlink(self):
        for employee in self:
            for model_name in self._BANK_SETTLEMENT_MODELS:
                if self.env[model_name].sudo().search_count(
                    [('employee_id', '=', employee.id)]
                ):
                    raise UserError(_(
                        'لا يمكن حذف الموظف "%s" نهائياً - له سجل/سجلات '
                        'سداد بنكي مرتبطة به (سلفة، رسوم حكومية، تأمين '
                        'طبي، تحويل مركبة، أو تصفية) يجب الحفاظ على '
                        'سجلها للتدقيق. استخدم "أرشفة" بدلاً من الحذف.'
                    ) % employee.name)
        return super().unlink()
