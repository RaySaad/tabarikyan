# -*- coding: utf-8 -*-
{
    'name': 'Recruitment Workflow - نموذج التسجيل على الموقع الإلكتروني',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'صفحة عامة على الموقع الإلكتروني لتسجيل المناديب الجدد',
    'description': """
نموذج تسجيل عام على الموقع الإلكتروني
=======================================
صفحة عامة (/careers/register) يسجّل فيها المرشّحون بياناتهم الأساسية
(الاسم، رقم الهوية/الإقامة، الجوال، الإيميل، الجنس، الجنسية، والمنصة التي
يرغبون بالتسجيل فيها)، فيُنشأ منها تلقائياً طلب توظيف في المرحلة الأولى
داخل موديول "Recruitment Workflow" الأساسي، ليتابعه الفريق الداخلي.

هذا الموديول منفصل عن الموديول الأساسي عمداً (بنفس منطق فصل Odoo نفسه
لـ hr_recruitment عن website_hr_recruitment) - فلا حاجة لاعتمادية
website على من لا يريد الواجهة العامة، ويسهل تطوير/تعديل كل جزء بمعزل
عن الآخر.
""",
    'author': 'Eng Osamah Almarhabi',
    'maintainer': 'Eng Osamah Almarhabi',
    'support': 'eng.osamarhbi@gmail.com',
    'website': 'mailto:eng.osamarhbi@gmail.com',
    'license': 'LGPL-3',
    'depends': [
        'recruitment_workflow',
        'website',
    ],
    'data': [
        'views/website_recruitment_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
