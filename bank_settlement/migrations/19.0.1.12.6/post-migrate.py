# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)

# ترتيب مهم: bank_settlement يعتمد على recruitment_workflow ويمدّد نموذج
# recruitment.request نفسه (يضيف حقولاً عليه) - هذا يجعل أودو يعيد
# "انعكاس" (_reflect_fields) حقول ذلك النموذج في كل مرة يُحمَّل فيها أي
# موديول لاحق يلمس نفس النموذج، وبما أن بيئة odoo.sh تحمّل ~343 موديولاً
# إجمالاً - أي موديول يُحمَّل بعد bank_settlement أبجدياً (والغالبية
# العظمى تُحمَّل بعده) قد يعيد تصفير الترجمة التي طُبِّقت للتو. أول
# محاولة (cr.postcommit) كانت تعمل محلياً فقط لأن اختباري شمل هذين
# الموديولين فقط (bank_settlement كان "آخر" موديول فعلياً في ذلك
# السياق المحدود) - فشلت على Staging الحقيقية حيث تتبعه عشرات
# الموديولات الأخرى. الحل: مهمة مجدولة (ir.cron) تُنفَّذ بعد دقيقة -
# بمعزل تام عن عملية تحميل الموديولات بالكامل. الدالة الفعلية معرَّفة في
# models/ir_cron.py (وليس هنا) لأن حقل "code" في ir.cron مُقيَّد بـ
# safe_eval ويمنع أي "import" - لا بد من استدعاء دالة بايثون حقيقية
# بسطر واحد فقط.
_ONE_TIME_CRON_NAME = 'مهمة مؤقتة: فرض تحميل ترجمة en_US (recruitment_workflow/bank_settlement)'


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    ir_cron_model = env['ir.model']._get_id('ir.cron')
    env['ir.cron'].sudo().create({
        'name': _ONE_TIME_CRON_NAME,
        'model_id': ir_cron_model,
        'state': 'code',
        'code': "env['ir.cron']._bank_settlement_force_load_en_translations()",
        # فترة تكرار طويلة جداً (100 سنة) عمداً: تنفَّذ مرة واحدة فعلياً
        # (بعد دقيقة من الإنشاء)، ثم يعيد أودو جدولتها تلقائياً لموعد بعيد
        # جداً - بديل بسيط وموثوق عن التعطيل الذاتي (الذي يفشل لأن تعديل
        # سجل ir.cron من داخل تنفيذه هو نفسه ممنوع في هذا الإصدار).
        'interval_number': 1200,
        'interval_type': 'months',
        'nextcall': datetime.now() + timedelta(minutes=1),
        'active': True,
    })
    _logger.info('bank_settlement: scheduled one-time cron to force-load en_US translations after full startup')
