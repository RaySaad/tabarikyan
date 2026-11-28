{
    'name': 'Quick Commerce Delivery Pro (30-Min SLA + OTP + Wallet + Live Map)',
    'version': '19.0.17.0.0',
    'author': 'Tabarikyan',
    'category': 'Operations/Logistics',
    'summary': 'Full 30-Min Supermarket Delivery: Auto-Dispatch, OTP POD, Driver COD Wallet, Failure Reasons & Live Map',
    'depends': ['base', 'web', 'bus', 'contacts'],
    'data': [
        'security/quick_delivery_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/delivery_views.xml',
        'views/driver_app_template.xml',
        'views/tracking_page_template.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'quick_delivery/static/src/scss/quick_delivery_home.scss',
            'quick_delivery/static/src/xml/quick_delivery_home.xml',
            'quick_delivery/static/src/js/quick_delivery_home.js',
            'quick_delivery/static/src/js/sla_dashboard.js',
            'quick_delivery/static/src/xml/sla_dashboard.xml',
        ],
    },
    # requests و pytz مثبّتتان مع أودو، لكن التصريح بهما يجعل العطل
    # واضحاً على بيئة مقلّصة بدل خطأ استيراد غامض وقت التحميل.
    'external_dependencies': {'python': ['requests', 'pytz',
                                         'cryptography', 'jwt']},
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
