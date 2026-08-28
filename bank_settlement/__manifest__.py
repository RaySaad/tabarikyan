# -*- coding: utf-8 -*-
{
    'name': 'السداد البنكي - Bank Settlement',
    'version': '19.0.1.12.7',
    'category': 'Accounting/Accounting',
    'summary': 'إدارة السلف، الرسوم الحكومية، تحويلات المركبات، التأمين الطبي، وتصفيات المناديب',
    'description': """
السداد البنكي (Bank Settlement)
================================
موديول يدير جميع المدفوعات البنكية المرتبطة بمناديب التوصيل:

- السلف (Advances)
- الرسوم الحكومية (Government Fees)
- تحويلات المركبات (Vehicle Transfers)
- التأمين الطبي (Medical Insurance)
- تصفيات المناديب (Representative Settlements)

تطبيق مستقل بأيقونته الخاصة (وليس مدموجاً داخل تطبيق المحاسبة) - حتى يقدر
مستخدمو السداد البنكي (مستخدم/محاسب) الدخول إليه دون الحاجة لأي صلاحية
محاسبية أصلية بـ Odoo، والتي كانت تفتح لهم أيضاً رؤية بقية تطبيق المحاسبة
(عملاء/موردين/فواتير) رغم عدم حاجتهم لها. يعتمد على موديول
recruitment_workflow لبيانات المناديب (hr.employee) والمنصات (project.project:
كيتا/هنقرستيشن/جاهز)، ويشتق الحساب التحليلي لكل منصة تلقائياً من مشروعها
بدل اختياره يدوياً بمعزل عنها. رقم الإقامة يُشتق مباشرة من ملف الموظف
(hr.employee.identification_id)، وشريكه الشخصي (لفواتير حصته من الرسوم)
يُستخدم عبر hr.employee._get_personal_partner() المعرّفة في recruitment_workflow.
    """,
    'author': 'Aidea - ذكاء الفكرة',
    'website': 'https://aidea.sa',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'hr',
        'project',
        'analytic',
        'recruitment_workflow',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/type_data.xml',
        'wizard/reject_wizard_views.xml',
        'wizard/return_wizard_views.xml',
        'wizard/employee_statement_wizard_views.xml',
        'views/type_views.xml',
        'views/advance_views.xml',
        'views/government_fee_views.xml',
        'views/vehicle_transfer_views.xml',
        'views/medical_insurance_views.xml',
        'views/representative_settlement_views.xml',
        'views/recruitment_request_views.xml',
        'views/menu_views.xml',
        'report/hr_employee_statement_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
