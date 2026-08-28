# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)

# حل نهائي (وليس مؤقتاً كسابقيه في 19.0.1.12.6/19.0.1.12.7): تلك النسختان
# جدولتا مهمة "لمرة واحدة فعلياً" (فترة تكرار 100 سنة) - تعمل بعد أول
# نشر فقط. المشكلة الحقيقية: _reflect_fields في أودو يعيد ضبط تسميات
# الحقول/القوائم للعربية الخام (المصدر) في *كل* تشغيل لاحق لـ-u يلمس
# نفس النماذج - أي كل رفعة جديدة لأي من الموديولين، وليس فقط عند إصدار
# هذا السكربت نفسه. الاعتماد على سكربت ترحيل جديد لكل إصدار مستقبلي هش
# (يعتمد على "التذكر يدوياً") - وهذا بالضبط ما حدث: توقفت الترجمة بعد
# عدة رفعات لاحقة لم تتضمن سكربت ترحيل جديد.
#
# الحل الدائم: نفس المهمة المجدولة تماماً (_bank_settlement_force_load_
# en_translations، مُختبرة وتعمل فعلياً)، لكن بفترة تكرار قصيرة وحقيقية
# (كل ساعة) بدل الحيلة أحادية التنفيذ - فتُعيد فرض الترجمة تلقائياً
# ذاتياً بعد أي رفعة مستقبلية، بلا حاجة لأي سكربت ترحيل جديد بعد الآن
# مهما تعدّدت الإصدارات اللاحقة. العملية رخيصة تماماً (بضع مئات من
# النصوص، عملية idempotent بالكامل) فتكرارها كل ساعة بلا ضرر يُذكر.
#
# ننظّف أولاً أي سجلات قديمة من المحاولتين السابقتين (لمرة واحدة) لتفادي
# تراكم سجلات مكرَّرة بلا فائدة.
_OLD_ONE_TIME_CRON_NAME = 'مهمة مؤقتة: فرض تحميل ترجمة en_US (recruitment_workflow/bank_settlement)'
_RECURRING_CRON_NAME = 'السداد البنكي: إعادة فرض ترجمة en_US/ar_001 دورياً (recruitment_workflow/bank_settlement)'


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    Cron = env['ir.cron'].sudo()

    old_crons = Cron.search([('name', '=', _OLD_ONE_TIME_CRON_NAME)])
    if old_crons:
        old_crons.unlink()
        _logger.info('bank_settlement: removed %d old one-time translation-fix cron(s)', len(old_crons))

    existing = Cron.search([('name', '=', _RECURRING_CRON_NAME)])
    if existing:
        existing.unlink()

    ir_cron_model = env['ir.model']._get_id('ir.cron')
    Cron.create({
        'name': _RECURRING_CRON_NAME,
        'model_id': ir_cron_model,
        'state': 'code',
        'code': "env['ir.cron']._bank_settlement_force_load_en_translations()",
        'interval_number': 1,
        'interval_type': 'hours',
        'nextcall': datetime.now() + timedelta(minutes=1),
        'active': True,
    })
    _logger.info(
        'bank_settlement: scheduled RECURRING (hourly) cron to force-load '
        'en_US/ar_001 translations - permanent fix, no future migration '
        'script needed for this specific issue again'
    )
