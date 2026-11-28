# -*- coding: utf-8 -*-
{
    'name': 'التوصيل الفوري: كشف حساب المندوب وطلب السلفة',
    'version': '19.0.1.0.3',
    'author': 'Tabarikyan',
    'category': 'Operations/Logistics',
    'summary': 'المندوب يرى كشف حسابه ويرفع طلب سلفة من تطبيقه',
    # جسر ثالث منفصل: التوصيل الفوري لا يعرف السداد البنكي ولا يجوز أن
    # يعرفه - وإلا صار تثبيت التوصيل يستلزم نظام السداد كاملاً.
    'depends': ['quick_delivery_hr_fleet', 'bank_settlement'],
    'data': [
        'views/driver_account_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
