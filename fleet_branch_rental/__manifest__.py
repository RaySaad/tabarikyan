# -*- coding: utf-8 -*-
{
    'name': 'أجرة الأسطول للفروع - Fleet Branch Rental',
    'version': '19.0.1.3.0',
    'category': 'Human Resources/Fleet',
    'summary': 'تحميل الفروع أجرة السيارات شهرياً، وتكاليف الحوادث بنسبة التحمل',
    'description': """
أجرة الأسطول للفروع
====================
شركة الأسطول تملك المركبات وتؤجّرها لفروع التشغيل. هذا الموديول
يحتسب التحميل الشهري ويرحّله محاسبياً.

السيناريو المعتمد:
- **عقد تأجير** يصدر بموافقة الأسطول على طلب السيارة في خطوة واحدة،
  وهو سجل الاستخدام ومصدر احتساب الأجرة. الملكية تبقى للأسطول.
- السيارة تُؤجَّر للفرع **شاملة الأعطال والصيانة الدورية** (على الأسطول).
- **الحوادث والتلفيات على الفرع** بنسبة تحمّله، ويستردّها من المندوب
  عند مسؤوليته عبر "تحويل مركبة" في السداد البنكي.
- عند حادث أو عطل كبير تُسلَّم السيارة للأسطول و**تتوقف الأجرة** من
  يوم التسليم.

الاحتساب لا يعتمد على تقدير: أيام تبعية كل مركبة لكل فرع مأخوذة من
"تاريخ فروع السيارات" المسجَّل أصلاً في سير عمل التوظيف، ويُغلقه
معالج النقل بتاريخه - فتسليم السيارة للأسطول يوقف الأجرة تلقائياً.

الرقم الضريبي واحد للمجموعة، فالتحميل **قيد داخلي لا فاتورة**: قيد
مصروف في الفرع مقابل حساب جارٍ، وقيد مقابل في الأسطول - يتقاصّان في
الميزانية الموحَّدة.
    """,
    'author': 'Aidea - ذكاء الفكرة',
    'website': 'https://aidea.sa',
    'license': 'LGPL-3',
    'depends': ['recruitment_workflow', 'bank_settlement', 'account', 'fleet'],
    'data': [
        'security/ir.model.access.csv',
        'security/fleet_branch_rental_security.xml',
        'data/sequence_data.xml',
        'views/fleet_vehicle_views.xml',
        'views/fleet_vehicle_idle_views.xml',
        'views/fleet_rental_contract_views.xml',
        'views/fleet_accident_report_views.xml',
        'views/fleet_branch_rental_charge_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/fleet_rental_opening_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
