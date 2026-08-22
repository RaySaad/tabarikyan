# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BankSettlementEmployeeStatementWizard(models.TransientModel):
    """معالج "كشف حساب الموظف" - يختار المستخدم الموظف وبداية فترة
    الكشف (من بداية العقد تلقائياً، أو تاريخ محدد يدوياً) قبل الطباعة.

    نموذج التقرير نفسه (action_report_hr_employee_statement) هو هذا
    المعالج - وليس hr.employee مباشرة - فتُقرأ قيم employee_id/date_from/
    date_to من حقول المعالج المخزَّنة فعلياً في قالب QWeb، بدل تمريرها
    عبر سياق الفتح (self.env.context) الذي قد لا يبقى مضموناً متاحاً
    عبر مسارات مختلفة لتنفيذ التقرير - نفس الدرس المستفاد من ثغرة
    return_wizard.py._selection_target_state (انظر شرحها المفصَّل هناك)."""
    _name = 'bank.settlement.employee.statement.wizard'
    _description = 'معالج طباعة كشف حساب الموظف'

    employee_id = fields.Many2one('hr.employee', string='الموظف', required=True)
    # طلب صريح: التقرير كان يعرض رأس/تذييل الشركة الحالية في الجلسة
    # (self.env.company)، وليس شركة/فرع الموظف نفسه - لأن web.external_
    # layout (القالب المعياري بأودو الذي يستدعيه القالب أدناه) يبحث عن
    # حقل company_id على السجل الرئيسي (doc) تحديداً؛ بدونه يقع تلقائياً
    # على الشركة الحالية كخيار احتياطي (انظر external_layout في web/
    # views/report_templates.xml). بإضافته هنا (related لشركة الموظف
    # نفسه - فرع منفصل فعلياً عن الشركة الرئيسية، تأكَّد المستخدم) يصبح
    # رأس/تذييل هذا التقرير تحديداً قابلاً للتعديل بحرية من إعدادات ذلك
    # الفرع (Settings > الشركات > [الفرع] > تذييل التقارير) بمعزل تام عن
    # تذييل الشركة الرئيسية المستخدَم في الفواتير وبقية التقارير - يحل
    # هذا وحده مشكلة "أريد حذف الآيبان هنا فقط، وليس بالفواتير" دون أي
    # كود إضافي، بمجرد أن يُعدِّل المستخدم تذييل ذلك الفرع تحديداً.
    company_id = fields.Many2one(
        'res.company', string='شركة/فرع الموظف',
        related='employee_id.company_id', store=True, readonly=True,
    )
    date_mode = fields.Selection(
        [('contract_start', 'من بداية العقد'), ('custom', 'تاريخ محدد')],
        string='بداية الكشف', default='contract_start', required=True,
    )
    date_from = fields.Date(
        string='من تاريخ',
        help='إلزامي فقط عند اختيار "تاريخ محدد" - يُحسَب تلقائياً من '
             'تاريخ بداية العقد عند اختيار "من بداية العقد".',
    )
    date_to = fields.Date(string='إلى تاريخ', default=fields.Date.context_today)

    @api.onchange('date_mode')
    def _onchange_date_mode(self):
        # يُفرَّغ الحقل عند التبديل إلى "من بداية العقد" - يُحسَب فعلياً
        # عند الطباعة (action_print) من عقد الموظف، وليس هنا (الموظف قد
        # يتغيّر بعد هذا الـ onchange).
        if self.date_mode == 'contract_start':
            self.date_from = False

    def _resolve_contract_start_date(self):
        """تاريخ بداية أحدث/أقدم عقد للموظف - بنفس منطق البحث المستخدم
        في recruitment_workflow.hr_employee._sync_contract_project()
        (current_version_id/version_id، ثم بحث احتياطي في hr.version/
        hr.contract). لا يوجد حد أدنى مضمون لو لم يوجد عقد إطلاقاً -
        يُرجَع False (يعني "بلا حد أدنى"، أي كل السجل التاريخي - أقرب
        تفسير عملي لـ"من بداية العقد" حين لا يوجد عقد مسجَّل أصلاً)."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        contract = False
        for fname in ('current_version_id', 'version_id'):
            if fname in employee._fields and employee[fname]:
                contract = employee[fname]
                break
        if not contract:
            for model_name in ('hr.version', 'hr.contract'):
                if model_name in self.env and 'employee_id' in self.env[model_name]._fields:
                    contract = self.env[model_name].sudo().search(
                        [('employee_id', '=', employee.id)],
                        limit=1, order='date_start asc',
                    )
                    if contract:
                        break
        if contract and 'date_start' in contract._fields:
            return contract.date_start
        return False

    def action_print(self):
        self.ensure_one()
        if not self.employee_id:
            raise UserError(_('اختر الموظف أولاً.'))
        if self.date_mode == 'custom' and not self.date_from:
            raise UserError(_('حدد "من تاريخ"، أو اختر "من بداية العقد".'))
        if self.date_mode == 'contract_start':
            # يُكتب على حقل السجل نفسه (وليس متغيّراً محلياً) - القيمة
            # يجب أن تصل لقالب QWeb عبر doc.date_from، بنفس فلسفة تخزين
            # القيم على المعالج نفسه الموضحة أعلاه.
            self.date_from = self._resolve_contract_start_date()
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise UserError(_('"إلى تاريخ" يجب أن يكون بعد أو يساوي "من تاريخ".'))
        return self.env.ref(
            'bank_settlement.action_report_hr_employee_statement'
        ).report_action(self)
