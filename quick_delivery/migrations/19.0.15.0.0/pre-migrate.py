# -*- coding: utf-8 -*-
"""حفظ مفاتيح التجّار النصّية قبل أن يصير الحقل محسوباً.

الحقل api_key كان مخزَّناً نصّاً وصار محسوباً (بصمته تُخزَّن بدله).
أودو تترك العمود القديم يتيماً، فنأخذ قيمه هنا قبل أن تُهمل - وإلا
توقّف العثيم وبندة عن الإرسال حتى تُعطيهم مفاتيح جديدة.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'api_key'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        DROP TABLE IF EXISTS qd_migration_api_keys;
        CREATE TABLE qd_migration_api_keys AS
        SELECT id AS partner_id, api_key
        FROM res_partner
        WHERE api_key IS NOT NULL AND TRIM(api_key) <> ''
    """)
    cr.execute('SELECT COUNT(*) FROM qd_migration_api_keys')
    _logger.info('التوصيل الفوري: حُفظ %d مفتاح تاجر للتعمية.',
                 cr.fetchone()[0])
    # القيد القديم على العمود النصّي لم يعد له معنى
    cr.execute('ALTER TABLE res_partner '
               'DROP CONSTRAINT IF EXISTS res_partner_qd_api_key_uniq')
