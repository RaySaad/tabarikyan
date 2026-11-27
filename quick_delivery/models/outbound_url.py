# -*- coding: utf-8 -*-
"""حارس الروابط الصادرة.

الخادم يستدعي روابط يكتبها المستخدم: رابط إبلاغ التاجر، ورابط مزوّد
الرسائل. ورابطٌ يشير إلى داخل الشبكة يجعل الخادم أداةً للوصول إلى ما
لا يصله المستخدم من الخارج - وأخطره **عنوان بيانات السحابة**
(169.254.169.254) الذي يُرجع بيانات اعتماد المثيل على المنصّات
السحابية.

هذا لا يحتاج اختراقاً: يكفي مديرٌ مخدوع أو حسابٌ مسروق.

وما يُسمح به قابل للضبط: من يُشغّل أودو في شبكته الداخلية قد يحتاج
رابطاً خاصاً فعلاً.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

ALLOW_PRIVATE_PARAM = 'quick_delivery.allow_private_urls'


class OutboundUrlError(Exception):
    """رابط صادر مرفوض."""


def check_outbound_url(env, url, label='الرابط'):
    """يرفع OutboundUrlError إن كان الرابط يشير إلى الشبكة الداخلية."""
    parsed = urlparse(url or '')
    if parsed.scheme not in ('http', 'https'):
        raise OutboundUrlError(
            '%s يجب أن يبدأ بـhttp أو https: %r' % (label, url))
    host = parsed.hostname
    if not host:
        raise OutboundUrlError('%s بلا اسم مضيف: %r' % (label, url))

    allow_private = (env['ir.config_parameter'].sudo()
                     .get_param(ALLOW_PRIVATE_PARAM, '').strip().lower()
                     in ('1', 'true', 'yes'))

    try:
        # كل العناوين لا الأول فقط: اسمٌ قد يُحلّ إلى عام وخاص معاً.
        infos = socket.getaddrinfo(host, None)
    except Exception:
        # تعذّر الحلّ: نتركه للطلب نفسه ليفشل برسالة الشبكة المعتادة،
        # ولا نمنع رابطاً قد يعمل لاحقاً.
        return
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_loopback or address.is_link_local \
                or address.is_reserved or address.is_multicast:
            raise OutboundUrlError(
                '%s يشير إلى عنوان داخلي ممنوع (%s).' % (label, address))
        if address.is_private and not allow_private:
            raise OutboundUrlError(
                '%s يشير إلى شبكة خاصة (%s). إن كان مقصوداً فعّل '
                'الإعداد %s.' % (label, address, ALLOW_PRIVATE_PARAM))
