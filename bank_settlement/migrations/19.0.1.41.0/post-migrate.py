# -*- coding: utf-8 -*-
"""يُزيل بقايا جدول "استرداد السلفة" بعد حذف الميزة.

أودو تحذف سجلات ir.model/ir.model.fields/الشاشات/الصلاحيات تلقائياً
لنموذج لم يعد معرَّفاً، لكنها *لا تحذف الجدول نفسه* - فيبقى جدولاً
يتيماً في قاعدة البيانات يربك من يقرأ المخطط لاحقاً.

يُحذف فقط إن كان فارغاً: وجود صفوف فيه يعني بيانات حقيقية سجّلها
أحد، ولا يجوز إتلافها بترقية موديول - تبقى حينها ليقرّر فيها المحاسب.
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = 'bank_settlement_advance_repayment'


def migrate(cr, version):
    cr.execute("SELECT to_regclass(%s)", ('public.%s' % TABLE,))
    row = cr.fetchone()
    if not row or not row[0]:
        return
    cr.execute('SELECT COUNT(*) FROM "%s"' % TABLE)
    count = cr.fetchone()[0]
    if count:
        _logger.warning(
            'bank_settlement: جدول %s فيه %s صفاً - تُرك كما هو بدل حذفه، '
            'لأن حذف بيانات مسجَّلة ليس من شأن ترقية موديول.', TABLE, count)
        return
    cr.execute('DROP TABLE "%s"' % TABLE)
    _logger.info('bank_settlement: حُذف جدول %s الفارغ بعد إزالة الميزة.', TABLE)
