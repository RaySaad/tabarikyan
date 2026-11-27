# -*- coding: utf-8 -*-
"""تعبئة الرسم والعمولة على الطلبات السابقة.

الرسم والعمولة صارا مثبَّتين على الطلب بدل قراءتهما من الإعداد
الحالي. الطلبات التي أُنشئت قبل ذلك تحمل صفراً، فتظهر تقارير الشهر
الماضي خاوية.

التعبئة هنا **تقديرية بالضرورة**: نكتب الإعداد الحالي للسوبرماركت
والمندوب، ولا سبيل لمعرفة ما كان ساريا وقت كل طلب - تلك البيانات لم
تكن تُحفظ أصلاً، وهذا هو الخلل الذي يُصلحه هذا الإصدار. الأرقام من
اليوم فصاعداً دقيقة.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE quick_delivery_order o
        SET delivery_fee = COALESCE(p.delivery_fee_per_order, 0.0)
        FROM res_partner p
        WHERE p.id = o.client_id
          AND COALESCE(o.delivery_fee, 0.0) = 0.0
          AND COALESCE(p.delivery_fee_per_order, 0.0) <> 0.0
    """)
    fees = cr.rowcount

    cr.execute("""
        UPDATE quick_delivery_order o
        SET driver_commission = COALESCE(d.commission_per_order, 0.0)
        FROM quick_delivery_driver d
        WHERE d.id = o.driver_id
          AND COALESCE(o.driver_commission, 0.0) = 0.0
          AND COALESCE(d.commission_per_order, 0.0) <> 0.0
    """)
    commissions = cr.rowcount

    # net_revenue محسوب ومخزَّن: نكتبه بنفس المعادلة بدل إعادة حساب
    # كامل على كل السجلات.
    cr.execute("""
        UPDATE quick_delivery_order
        SET net_revenue = COALESCE(delivery_fee, 0.0)
                          - COALESCE(driver_commission, 0.0)
    """)

    _logger.info('التوصيل الفوري: عُبّئ رسم %d طلب وعمولة %d طلب '
                 '(تقديراً من الإعداد الحالي).', fees, commissions)
