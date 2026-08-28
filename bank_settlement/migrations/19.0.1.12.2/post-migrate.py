# -*- coding: utf-8 -*-
import logging
import os

import odoo
from odoo.modules.module import get_module_path
from odoo.tools.translate import TranslationImporter

_logger = logging.getLogger(__name__)

# ترتيب مهم: bank_settlement يعتمد على recruitment_workflow ويمدّد نموذج
# recruitment.request نفسه (يضيف حقولاً عليه) - هذا يجعل أودو يعيد
# "انعكاس" (_reflect_fields) كل حقول ذلك النموذج أثناء تحميل bank_settlement
# نفسه، بعد أن يكون سكربت ترقية recruitment_workflow قد صحّح ترجمتها
# بالفعل - فيعيدها لنصها العربي الأصلي من جديد (تأكدنا تجريبياً: نفس
# الإصلاح المؤجَّل في recruitment_workflow وحده لا يكفي إن ثُبِّت
# bank_settlement بعده في نفس عملية الترقية). الحل: bank_settlement - بصفته
# آخر حلقة في سلسلة الاعتماد هنا - يعيد تحميل ترجمتَي الموديولين معاً بعد
# انتهاء التحميل بالكامل (عبر postcommit)، فتكون الكتابة الأخيرة الفعلية.
_MODULES = ['recruitment_workflow', 'bank_settlement']


def migrate(cr, version):
    po_paths = []
    for module_name in _MODULES:
        module_path = get_module_path(module_name)
        if not module_path:
            continue
        po_path = os.path.join(module_path, 'i18n', 'en.po')
        if os.path.exists(po_path):
            po_paths.append((module_name, po_path))

    def _force_load_en_translations():
        db_name = cr.dbname
        new_cr = odoo.sql_db.db_connect(db_name).cursor()
        try:
            importer = TranslationImporter(new_cr, verbose=False)
            for module_name, po_path in po_paths:
                importer.load_file(po_path, 'en_US')
            importer.save(overwrite=True, force_overwrite=True)
            new_cr.commit()
            _logger.info(
                'bank_settlement: force-loaded en_US translations for %s (deferred, post dependency chain)',
                ', '.join(m for m, _p in po_paths),
            )
        finally:
            new_cr.close()

    cr.postcommit.add(_force_load_en_translations)
