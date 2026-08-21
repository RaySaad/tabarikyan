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

    # -- كشف حساب الموظف (طباعة) -----------------------------------------
    # طلب صريح: تقرير يُعطى للموظف نفسه، يقتصر على ما "يخصه" فعلياً -
    # مبالغ ذهبت له (سلف، تصفيات مناديب، رواتب/عمولات)، ومخالفات/رسوم
    # رخصة مركبته تحديداً. الرسوم الحكومية والتأمين الطبي مستبعدان عمداً
    # (مصاريف داخلية للشركة، لا علاقة مباشرة للموظف بها من منظوره هو).
    _VEHICLE_TRANSFER_STATEMENT_TYPES = (
        'bank_settlement.vehicle_transfer_type_traffic_violation',
        'bank_settlement.vehicle_transfer_type_driving_license',
    )

    def _get_employee_statement_data(self):
        """يجمع كل بيانات كشف حساب الموظف - انظر الشرح أعلاه لسبب
        استبعاد الرسوم الحكومية/التأمين الطبي عمداً."""
        self.ensure_one()
        advances = self.env['bank.settlement.advance'].sudo().search(
            [('employee_id', '=', self.id)], order='create_date desc',
        )
        settlements = self.env['bank.settlement.representative'].sudo().search(
            [('employee_id', '=', self.id)], order='create_date desc',
        )
        statement_type_ids = [
            xmlid_id for xmlid_id in (
                self.env.ref(xmlid, raise_if_not_found=False).id
                for xmlid in self._VEHICLE_TRANSFER_STATEMENT_TYPES
            ) if xmlid_id
        ]
        vehicle_transfers = self.env['bank.settlement.vehicle.transfer'].sudo().search(
            [
                ('employee_id', '=', self.id),
                ('transfer_type_id', 'in', statement_type_ids),
            ], order='create_date desc',
        )
        # رواتب/عمولات: قيود محاسبية مرحّلة على شريكه الشخصي، باستثناء
        # القيود التي أنشأها السداد البنكي نفسه (is_bank_settlement_move)
        # - وإلا تكرّرت نفس السلفة/التصفية مرتين (مرة كسجل سداد بنكي،
        # ومرة كسطر قيد محاسبي على نفس الشريك).
        partner = self.sudo()._get_personal_partner()
        payroll_lines = self.env['account.move.line'].sudo().search(
            [
                ('partner_id', '=', partner.id),
                ('move_id.is_bank_settlement_move', '=', False),
                ('move_id.state', '=', 'posted'),
                ('display_type', '=', 'payment_term'),
            ], order='date desc',
        ) if partner else self.env['account.move.line']
        payroll_total = sum(
            (line.credit or line.debit) for line in payroll_lines
        )
        total = (
            sum(advances.mapped('amount'))
            + sum(settlements.mapped('settlement_amount'))
            + sum(vehicle_transfers.mapped('amount'))
            + payroll_total
        )
        return {
            'advances': advances,
            'settlements': settlements,
            'vehicle_transfers': vehicle_transfers,
            'payroll_lines': payroll_lines,
            'payroll_total': payroll_total,
            'total': total,
        }

    def action_print_employee_statement(self):
        self.ensure_one()
        return self.env.ref(
            'bank_settlement.action_report_hr_employee_statement'
        ).report_action(self)
