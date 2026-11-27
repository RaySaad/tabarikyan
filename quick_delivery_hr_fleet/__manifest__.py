# -*- coding: utf-8 -*-
{
    'name': 'التوصيل الفوري: ربط المندوبين بالموظفين والأسطول',
    'version': '19.0.1.0.0',
    'author': 'Tabarikyan',
    'category': 'Operations/Logistics',
    'summary': 'يربط مندوب التوصيل بملف الموظف وبمركبة الأسطول',
    # موديول جسر منفصل عمداً: quick_delivery يجب أن يبقى قابلاً
    # للتثبيت بلا الموارد البشرية ولا الأسطول - ومن لا يحتاج الربط لا
    # يُفرض عليه تطبيقان.
    'depends': ['quick_delivery', 'hr', 'fleet'],
    'data': [
        'views/driver_link_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
