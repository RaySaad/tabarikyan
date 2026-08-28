# -*- coding: utf-8 -*-
import logging
import os

import odoo
from odoo.modules.module import get_module_path
from odoo.tools.translate import TranslationImporter

_logger = logging.getLogger(__name__)

_MODULE = 'recruitment_workflow'


def migrate(cr, version):
    """يحمّل ترجمة i18n/en.po بالقوة (force_overwrite=True) - انظر شرح
    كامل في bank_settlement.migrations نظيرتها.

    مؤجَّل عبر cr.postcommit عمداً: أودو نفسه يستدعي
    ir.module.module._update_translations() *بعد* migrate(post) مباشرة
    (loading.py) بصلاحية overwrite عادية (غير force) - وبما أن قيمة
    en_US تغيّرت للتو (إنجليزي بدل عربي)، تلك الاستدعاءة اللاحقة تعيد
    مطابقة نفس ملف po ضد القيمة الجديدة فتُفسِد التغيير أحياناً (تأكدنا
    تجريبياً). تأجيل التنفيذ الفعلي حتى commit() الرئيسي يضمن أن يكون
    تحميلنا آخر كتابة فعلية، بعد أن ينتهي أودو من مساره القياسي بالكامل."""
    module_path = get_module_path(_MODULE)
    po_path = os.path.join(module_path, 'i18n', 'en.po')
    if not os.path.exists(po_path):
        _logger.warning('%s: en.po not found at %s, skipping', _MODULE, po_path)
        return

    def _force_load_en_translations():
        db_name = cr.dbname
        new_cr = odoo.sql_db.db_connect(db_name).cursor()
        try:
            importer = TranslationImporter(new_cr, verbose=False)
            importer.load_file(po_path, 'en_US')
            importer.save(overwrite=True, force_overwrite=True)
            new_cr.commit()
            _logger.info('%s: force-loaded en_US translations from i18n/en.po (deferred)', _MODULE)
        finally:
            new_cr.close()

    cr.postcommit.add(_force_load_en_translations)
