# -*- coding: utf-8 -*-
{
    'name': 'التوصيل الفوري: ربط المندوبين بالموظفين والأسطول',
    'version': '19.0.2.1.0',
    'author': 'Tabarikyan',
    'category': 'Operations/Logistics',
    'summary': 'يربط مندوب التوصيل بملف الموظف وبمركبة الأسطول',
    # موديول جسر منفصل عمداً: quick_delivery يجب أن يبقى قابلاً
    # للتثبيت بلا الموارد البشرية ولا الأسطول - ومن لا يحتاج الربط لا
    # يُفرض عليه تطبيقان.
    # hr_work_entry اعتماد صريح: views/hr_work_entry_groups.xml يستهدف
    # زر "فتح إدخالات العمل" المُعرَّف فيه. وبدون الاعتماد لا ترتيب
    # مضمون بين الموديولين، فقد يُحمَّل بعدنا ويفشل الـxpath.
    'depends': ['quick_delivery', 'hr', 'fleet', 'hr_work_entry'],
    'data': [
        'security/ir.model.access.csv',
        # أولاً قبل أي عرض يمسّ بطاقة الموظف: يقيّد زر إدخالات العمل
        # ليطابق صلاحية حقله، وإلا أطلق أول عرضٍ منّا على النموذج تحذير
        # "عدم اتساق في صلاحيات الوصول" (الشرح في الملف نفسه).
        'views/hr_work_entry_groups.xml',
        # المعالج قبل الشاشات: زر بطاقة الموظف يشير إلى إجراء المعالج،
        # والترتيب العكسي يُسقط التثبيت بـ"External ID not found".
        'views/make_driver_views.xml',
        'views/driver_link_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
