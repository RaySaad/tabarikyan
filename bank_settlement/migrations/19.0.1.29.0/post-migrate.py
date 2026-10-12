# -*- coding: utf-8 -*-
"""يحذف المهمة المجدولة التي تُعيد فرض الترجمات كل ساعة.

المهمة أُنشئت علاجاً لمشكلة حقيقية: النصوص العربية كانت مخزَّنة تحت
مفتاح "en_US"، فحاولت إصلاحاً أول استبدلها بالإنجليزية فرأى المستخدم
العربي إنجليزيةً. فجُعل الإصلاح دورياً "ضماناً" لعدم عودتها.

والثمن ظهر في الاستخدام: الإصلاح يستورد ملفَّي .po بـforce_overwrite،
وهما يحملان أسماء سجلات البيانات المترجَمة - أنواع مرفقات التوظيف
وأنواع الإنذارات وأسباب السلف وأنواع الرسوم وفئات الدفعة المقدمة
وأسماء المراحل. فكل تسمية يغيّرها المستخدم تعود لأصلها خلال ساعة.
بلّغ المستخدم فعلياً: "كلما غيّرت أسماء أنواع المرفقات ترجع القديمة".

الإصلاح الأصلي تمّ وانعكس في قاعدة البيانات، وترقيات أودو العادية
تستورد الترجمات بلا استبدال للقيم القائمة - فتصمد تعديلات المستخدم.
والدالة نفسها (ir_cron._bank_settlement_force_load_en_translations)
تبقى موجودة لتُستدعى يدوياً مرة واحدة إن لزم الأمر مستقبلاً.
"""
import logging

from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)

_CODE_MARK = '_bank_settlement_force_load_en_translations'


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    crons = env['ir.cron'].sudo().with_context(active_test=False).search([
        ('code', 'like', _CODE_MARK),
    ])
    if not crons:
        _logger.info('bank_settlement: لا مهمة فرض ترجمات لحذفها')
        return
    names = crons.mapped('name')
    crons.unlink()
    _logger.info(
        'bank_settlement: حُذفت %d مهمة فرض ترجمات - التسميات اليدوية '
        'صارت تصمد (%s)', len(names), ' | '.join(names))
