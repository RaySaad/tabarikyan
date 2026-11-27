# -*- coding: utf-8 -*-
"""قبل الترقية: حفظ المندوبين القدامى وفكّ ارتباط الطلبات بهم.

المندوب كان مستخدم أودو (res.users)، وصار كياناً مستقلاً
(quick.delivery.driver). العمود driver_id نفسه باقٍ (رقم صحيح) لكن
مرجعه تغيّر، فمفتاحه الأجنبي الجديد يرفض كل صف يحمل رقم مستخدم:

    ERROR: insert or update on table "quick_delivery_order"
    violates foreign key constraint "quick_delivery_order_driver_id_fkey"

هنا نُفرّغ العمود ونحفظ الخريطة، وفي post-migrate نُنشئ المندوبين
ونُعيد الربط. بلا هذين الملفين تفشل الترقية كلها وتبقى القاعدة على
النسخة القديمة.
"""
import logging

_logger = logging.getLogger(__name__)


def _has_column(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return

    if not _has_column(cr, 'res_users', 'is_delivery_driver'):
        _logger.info('لا مندوبين على res.users - لا شيء يُرحَّل.')
        return

    # 1) المندوبون القدامى، مع أسمائهم وجوالاتهم من بطاقة الشريك.
    cr.execute("""
        DROP TABLE IF EXISTS qd_migration_drivers;
        CREATE TABLE qd_migration_drivers AS
        SELECT u.id                                    AS user_id,
               COALESCE(NULLIF(TRIM(p.name), ''),
                        'مندوب رقم ' || u.id::text)    AS name,
               NULLIF(TRIM(p.phone), '')              AS phone,
               u.driver_status                         AS driver_status,
               u.current_lat                           AS current_lat,
               u.current_lng                           AS current_lng,
               u.last_ping                             AS last_ping,
               u.commission_per_order                  AS commission_per_order,
               NULL::integer                           AS new_driver_id
        FROM res_users u
        JOIN res_partner p ON p.id = u.partner_id
        WHERE u.is_delivery_driver IS TRUE
    """)
    cr.execute('SELECT COUNT(*) FROM qd_migration_drivers')
    driver_count = cr.fetchone()[0]

    # 2) خريطة الطلبات ← المستخدم، قبل تفريغ العمود.
    cr.execute("""
        DROP TABLE IF EXISTS qd_migration_order_driver;
        CREATE TABLE qd_migration_order_driver AS
        SELECT id AS order_id, driver_id AS user_id
        FROM quick_delivery_order
        WHERE driver_id IS NOT NULL
    """)
    cr.execute('SELECT COUNT(*) FROM qd_migration_order_driver')
    order_count = cr.fetchone()[0]

    # 3) تفريغ العمود وإسقاط المفتاح الأجنبي القديم ليُعاد بناؤه.
    cr.execute('ALTER TABLE quick_delivery_order '
               'DROP CONSTRAINT IF EXISTS quick_delivery_order_driver_id_fkey')
    cr.execute('UPDATE quick_delivery_order SET driver_id = NULL '
               'WHERE driver_id IS NOT NULL')

    _logger.info('ترحيل التوصيل الفوري: حُفظ %d مندوباً و%d طلباً مرتبطاً.',
                 driver_count, order_count)
