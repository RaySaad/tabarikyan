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
        """يعيد تحميل ترجمتَي en_US وar_001 لكلا الموديولين بالقوة
        (force_overwrite).

        لماذا ar_001 أيضاً وليس en_US فقط: النصوص المصدرية في هذين
        الموديولين عربية، وكانت مخزَّنة *داخل مفتاح "en_US" نفسه*
        (`{"en_US": "نص عربي"}`) - لا يوجد مفتاح "ar_001" منفصل كان
        موجوداً من قبل؛ أودو يستخدم "en_US" كاحتياطي شامل لأي لغة بلا
        ترجمة خاصة بها، فكان المستخدمون العرب يعرضون هذا النص عبر ذلك
        الاحتياطي أصلاً. أول محاولة استبدلت "en_US" بالإنجليزي مباشرة -
        فحذفت فعلياً النسخة العربية الوحيدة الموجودة لتلك النصوص، وصار
        المستخدم العربي يرى الإنجليزي أيضاً (اكتشفه المستخدم فعلياً بعد
        النشر). الإصلاح: نحمّل ar_001.po أولاً (نسخة الأصل العربي نفسه،
        ليُخزَّن تحت مفتاحه الخاص) ثم en.po - كلاهما ضمن نفس دفعة
        التحميل قبل استدعاء save() مرة واحدة لكل موديول، حتى تُطابَق
        القيمة العربية الأصلية بشكل صحيح لكلا اللغتين معاً (قبل أن
        يُستبدَل مفتاح en_US بالإنجليزي).

        سبب وجود هذه الدالة (بدل تنفيذ الكود مباشرة داخل حقل "code" في
        ir.cron): ذلك الحقل مُقيَّد بـsafe_eval ويمنع أي "import" - لا بد
        من دالة بايثون عادية غير مقيَّدة (معرَّفة في ملف .py حقيقي) تُستدعى
        من هناك بسطر واحد فقط. وسبب التأجيل عبر ir.cron بالكامل: انظر شرح
        كامل في migrations/19.0.1.12.5/post-migrate.py (مشكلة إعادة
        انعكاس الحقول عبر سلسلة الموديولات المعتمدة)."""
        for module_name in ('recruitment_workflow', 'bank_settlement'):
            module_path = get_module_path(module_name)
            if not module_path:
                continue
            importer = TranslationImporter(self.env.cr, verbose=False)
            ar_path = os.path.join(module_path, 'i18n', 'ar_001.po')
            en_path = os.path.join(module_path, 'i18n', 'en.po')
            if os.path.exists(ar_path):
                importer.load_file(ar_path, 'ar_001')
            if os.path.exists(en_path):
                importer.load_file(en_path, 'en_US')
            importer.save(overwrite=True, force_overwrite=True)

        # save() يكتب مباشرة في قاعدة البيانات (SQL خام) لتفادي قيد
        # "Record cannot be modified"/عدم دعم force_overwrite عبر المسار
        # العادي - هذا يتجاوز آلية إبطال الذاكرة المؤقتة (cache
        # invalidation) التي تُفعَّل تلقائياً عادة عند الكتابة عبر ORM
        # العادي. بنية القوائم (menus) تحديداً مخزَّنة مؤقتاً لكل (مستخدم/
        # لغة) - بلا هذا التفريغ الصريح، يستمر عرض القوائم القديمة رغم
        # صحة القيمة الفعلية في قاعدة البيانات. clear_all_caches تُبلِّغ
        # أيضاً بقية عمليات الخادم (workers) تلقائياً عبر آلية أودو
        # المدمجة، وليس فقط العملية الحالية.
        self.env.registry.clear_all_caches()
        self.env.cr.commit()
        _logger.info('bank_settlement: force-loaded ar_001/en_US translations and cleared all caches (deferred one-time cron)')
        # لا تعطيل يدوي هنا عمداً: تعديل سجل ir.cron من داخل تنفيذه هو
        # نفسه يفشل بـ"Record cannot be modified right now" (أودو يقفل
        # السجل أثناء التشغيل). بدلاً من ذلك، فترة التكرار في سكربت
        # الترقية طويلة جداً (100 سنة) - فيعيد أودو جدولتها تلقائياً لموعد
        # بعيد جداً بعد أول تنفيذ ناجح، بلا حاجة لأي تعطيل صريح.
