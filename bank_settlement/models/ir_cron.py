# -*- coding: utf-8 -*-
import logging
import os

from odoo import api, models
from odoo.modules.module import get_module_path
from odoo.tools.translate import TranslationImporter

_logger = logging.getLogger(__name__)


class IrCron(models.Model):
    _inherit = 'ir.cron'

    @api.model
    def _bank_settlement_force_load_en_translations(self):
        """يعيد تحميل ترجمة en.po لكلا الموديولين بالقوة (force_overwrite).

        سبب وجود هذه الدالة (بدل تنفيذ الكود مباشرة داخل حقل "code" في
        ir.cron): ذلك الحقل مُقيَّد بـsafe_eval ويمنع أي "import" - لا بد
        من دالة بايثون عادية غير مقيَّدة (معرَّفة في ملف .py حقيقي) تُستدعى
        من هناك بسطر واحد فقط. انظر شرح سبب الحاجة لهذا التأجيل بالكامل
        في migrations/19.0.1.12.4/post-migrate.py."""
        for module_name in ('recruitment_workflow', 'bank_settlement'):
            module_path = get_module_path(module_name)
            if not module_path:
                continue
            po_path = os.path.join(module_path, 'i18n', 'en.po')
            if not os.path.exists(po_path):
                continue
            importer = TranslationImporter(self.env.cr, verbose=False)
            importer.load_file(po_path, 'en_US')
            importer.save(overwrite=True, force_overwrite=True)
        self.env.cr.commit()
        _logger.info('bank_settlement: force-loaded en_US translations (deferred one-time cron)')
        # لا تعطيل يدوي هنا عمداً: تعديل سجل ir.cron من داخل تنفيذه هو
        # نفسه يفشل بـ"Record cannot be modified right now" (أودو يقفل
        # السجل أثناء التشغيل). بدلاً من ذلك، فترة التكرار في سكربت
        # الترقية طويلة جداً (100 سنة) - فيعيد أودو جدولتها تلقائياً لموعد
        # بعيد جداً بعد أول تنفيذ ناجح، بلا حاجة لأي تعطيل صريح.
