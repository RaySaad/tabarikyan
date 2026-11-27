# -*- coding: utf-8 -*-
"""تعمية مفاتيح التجّار المحفوظة، ثم إسقاط العمود النصّي.

المفاتيح القائمة تبقى عاملة: نُعمّيها كما هي، فلا ينقطع تاجر ولا
تُغيَّر مفاتيح متّفق عليها. وإسقاط العمود بعدها هو الغرض - بقاؤه
يُبقي النصّ في كل نسخة احتياطية.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT 1 FROM information_schema.tables "
               "WHERE table_name = 'qd_migration_api_keys'")
    if not cr.fetchone():
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Partner = env['res.partner'].sudo()
    cr.execute('SELECT partner_id, api_key FROM qd_migration_api_keys')

    migrated = 0
    short = 0
    for partner_id, key in cr.fetchall():
        partner = Partner.browse(partner_id).exists()
        if not partner or not key:
            continue
        key = key.strip()
        # نكتب البصمة مباشرةً لا عبر الحقل: مفتاح قديم قد يكون أقصر
        # من الحدّ الأدنى الجديد، ورفضه هنا يقطع تاجراً يعمل اليوم.
        partner.write({
            'api_key_index': Partner._qd_api_key_index(key),
            'api_key_hash': Partner._qd_api_key_hash(key),
        })
        migrated += 1
        if len(key) < 24:
            short += 1
            _logger.warning(
                'مفتاح التاجر "%s" قصير (%d حرفاً) - يعمل، لكن ولّد له '
                'مفتاحاً جديداً.', partner.name, len(key))

    cr.execute('ALTER TABLE res_partner DROP COLUMN IF EXISTS api_key')
    cr.execute('DROP TABLE IF EXISTS qd_migration_api_keys')
    _logger.info('التوصيل الفوري: عُمّي %d مفتاح تاجر (%d منها قصير)، '
                 'وأُسقط العمود النصّي.', migrated, short)
