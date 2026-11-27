# -*- coding: utf-8 -*-
"""بعد الترقية: إنشاء المندوبين الجدد وإعادة ربط الطلبات بهم.

يُكمل ما بدأه pre-migrate. النتيجة: تاريخ التوصيل كاملاً - من أوصل
أي طلب، والعهدة غير المسوّاة - ينتقل إلى الكيان الجديد بلا فقد.

ما لا يُرحَّل عمداً: **رمز الدخول**. القديم رمزٌ نصّي أبدي، والجديد
رمز سري مُعمّى. كل مندوب يحتاج "توليد رمز دخول" مرة واحدة - وهذا
مقصود، فالرموز القديمة كانت تُقرأ من قاعدة البيانات.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute("SELECT 1 FROM information_schema.tables "
               "WHERE table_name = %s", (table,))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version or not _table_exists(cr, 'qd_migration_drivers'):
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Driver = env['quick.delivery.driver']

    cr.execute("""
        SELECT user_id, name, phone, driver_status, current_lat,
               current_lng, last_ping, commission_per_order
        FROM qd_migration_drivers ORDER BY user_id
    """)
    rows = cr.fetchall()

    used_keys = set(Driver.with_context(active_test=False).search(
        []).mapped('login_key'))
    mapping = {}

    for (user_id, name, phone, status, lat, lng, ping, commission) in rows:
        key = Driver._phone_key(phone)
        if len(key) < 9 or key in used_keys:
            # جوال ناقص أو مكرر: رقم بديل صالح شكلاً يُصحّحه المدير.
            # الأهم ألا نفقد المندوب وتاريخه لأجل حقل ناقص.
            phone = '9%08d' % user_id
            key = Driver._phone_key(phone)
            _logger.warning(
                'المندوب "%s" (user %s) بلا جوال صالح أو مكرر - '
                'أُعطي رقماً مؤقتاً %s، يجب تصحيحه قبل أن يدخل التطبيق.',
                name, user_id, phone)
        used_keys.add(key)

        driver = Driver.create({
            'name': name,
            'phone': phone,
            # الحالة تبدأ "غير متصل": الجلسات القديمة لا تُرحَّل، فلا
            # معنى لمندوب "متاح" ولا تطبيق بيده.
            'driver_status': 'offline',
            'current_lat': lat or 0.0,
            'current_lng': lng or 0.0,
            'last_ping': ping,
            'commission_per_order': commission or 8.0,
            'notes': 'رُحِّل من مستخدم أودو رقم %s. يحتاج "توليد رمز '
                     'دخول" قبل أن يستعمل التطبيق.' % user_id,
        })
        mapping[user_id] = driver.id
        cr.execute('UPDATE qd_migration_drivers SET new_driver_id = %s '
                   'WHERE user_id = %s', (driver.id, user_id))

    # إعادة ربط الطلبات
    cr.execute("""
        UPDATE quick_delivery_order o
        SET driver_id = d.new_driver_id
        FROM qd_migration_order_driver m
        JOIN qd_migration_drivers d ON d.user_id = m.user_id
        WHERE o.id = m.order_id AND d.new_driver_id IS NOT NULL
    """)
    relinked = cr.rowcount

    # إعادة ضبط حالة من عليه طلب حيّ فعلاً
    Driver.browse(list(mapping.values()))._qd_refresh_status()

    # تنظيف: الأعمدة القديمة على res.users لم تعد تعني شيئاً، ومنها
    # رمز دخول نصّي لا سبب لبقائه في قاعدة البيانات.
    for column in ('is_delivery_driver', 'driver_token', 'driver_status',
                   'current_lat', 'current_lng', 'last_ping',
                   'commission_per_order'):
        cr.execute('ALTER TABLE res_users DROP COLUMN IF EXISTS "%s"'
                   % column)

    cr.execute('DROP TABLE IF EXISTS qd_migration_order_driver')
    cr.execute('DROP TABLE IF EXISTS qd_migration_drivers')

    _logger.info('ترحيل التوصيل الفوري: أُنشئ %d مندوباً، '
                 'وأُعيد ربط %d طلباً.', len(mapping), relinked)
