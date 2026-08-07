# -*- coding: utf-8 -*-
{
    'name': 'السداد البنكي - Bank Settlement',
    'version': '19.0.1.0.0',
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

مدموج داخل تطبيق المحاسبة نفسه (وليس تطبيقاً مستقلاً) - يعتمد على موديول
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
        'views/advance_views.xml',
        'views/government_fee_views.xml',
        'views/vehicle_transfer_views.xml',
        'views/medical_insurance_views.xml',
        'views/representative_settlement_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    # يُعاد ربط القائمة الجذرية تلقائياً تحت تطبيق "المحاسبة" الحقيقي
    # (Enterprise: موديول accountant) إن كان مثبتاً، بدل "الفوترة"
    # الافتراضية في Community - انظر hooks.py.
    'post_init_hook': '_post_init_hook',
}
