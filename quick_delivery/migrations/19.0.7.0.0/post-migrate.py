# -*- coding: utf-8 -*-
"""رمز رابط التتبع للطلبات السابقة.

بلا رمز لا رابط، فطلبات ما قبل هذا الإصدار لا يستطيع أصحابها تتبّعها.
نولّده هنا بـsecrets لا بأي مشتقّ من رقم الطلب: رقم متسلسل يُخمَّن،
فيقرأ أي أحد رمز تسليم أي طلب.
"""
import logging
import secrets

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT id FROM quick_delivery_order "
               "WHERE tracking_token IS NULL OR tracking_token = ''")
    ids = [row[0] for row in cr.fetchall()]
    for order_id in ids:
        cr.execute('UPDATE quick_delivery_order SET tracking_token = %s '
                   'WHERE id = %s', (secrets.token_urlsafe(24), order_id))
    _logger.info('التوصيل الفوري: وُلّد رمز تتبع لـ%d طلب سابق.', len(ids))
