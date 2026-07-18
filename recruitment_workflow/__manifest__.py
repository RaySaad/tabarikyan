# -*- coding: utf-8 -*-
{
    'name': 'Recruitment Workflow - سير عمل طلبات التوظيف',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'نظام إدارة مراحل طلبات التوظيف ونقل الكفالة وطلب السيارات وإنشاء العقود',
    'description': """
نظام سير عمل طلبات التوظيف
============================
موديول متكامل لإدارة دورة حياة طلب التوظيف عبر مراحل معتمدة:

* طلب جديد (تحديد نظام التشغيل والتطبيق الرئيسي)
* قيد المراجعة - مسؤول المشروع (موافقة / تعديل)
* مراجعة مدير العمليات (موافقة / رفض)
* اعتماد المدير العام (موافقة / رفض)
* تم السداد
* جاري نقل الكفالة
* تم نقل الكفالة - الموارد البشرية
* طلب سيارة - مسؤول المشروع (ربط مع الأسطول)
* تم مباشرة العمل (إنشاء عقد أوتوماتيك)

المميزات:
---------
* التحقق من رقم الهوية (10 أرقام، تبدأ بـ 1 أو 2)
* التحقق من رقم الجوال السعودي
* المرفقات الإجبارية قبل الانتقال للمرحلة التالية
* ربط مع أسطول السيارات (fleet) - لا يمكن الانتقال بدون سيارة متاحة
* إنشاء عقد عمل أوتوماتيكي عند توفر وحدة العقود (Payroll/Enterprise)، وإلا إنشاء سجل الموظف
* متوافق مع Odoo Community و Enterprise (اعتماد مرن على وحدة العقود)
* ربط كل مندوب بمشروع/منصة توصيل (كيتا، هنقرستيشن...) عبر project.project لفصل
  المتابعة والحسابات (Analytic Account) تلقائياً لكل منصة
* نقل المندوب بين المنصات مع سجل تاريخي كامل بالتواريخ (بدون فقدان بيانات المنصة السابقة)
* ربط محاسبي كامل بالمشروع/المنصة: الرواتب (عبر الحساب التحليلي على العقد)،
  وتكاليف تجديد الإقامة/النقل/أي تكلفة أخرى (قيد محاسبي تلقائي موزّع تحليلياً)
""",
    'author': 'Eng Osamah Almarhabi',
    'maintainer': 'Eng Osamah Almarhabi',
    'support': 'eng.osamarhbi@gmail.com',
    'website': 'mailto:eng.osamarhbi@gmail.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_recruitment',
        'fleet',
        'project',
        'analytic',
        'account',
    ],
    'data': [
        'security/recruitment_workflow_security.xml',
        'security/ir.model.access.csv',
        'data/recruitment_workflow_sequence.xml',
        'data/recruitment_workflow_data.xml',
        'data/account_journal_data.xml',
        'data/mail_templates.xml',
        'wizard/recruitment_reject_wizard_views.xml',
        'wizard/recruitment_return_wizard_views.xml',
        'wizard/hr_employee_platform_transfer_wizard_views.xml',
        'wizard/hr_employee_platform_bulk_assign_wizard_views.xml',
        'views/recruitment_request_views.xml',
        'views/recruitment_stage_views.xml',
        'views/recruitment_attachment_type_views.xml',
        'views/recruitment_compensation_type_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/project_project_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_cost_views.xml',
        'views/recruitment_workflow_menus.xml',
        'reports/recruitment_request_report.xml',
    ],
    'demo': [
        'data/recruitment_workflow_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'recruitment_workflow/static/src/scss/recruitment_workflow.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'external_dependencies': {
        'python': [],
    },
}
