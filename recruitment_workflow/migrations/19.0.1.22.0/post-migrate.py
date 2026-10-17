# -*- coding: utf-8 -*-
"""تحرير جهات اتصال السائقين من ملكية الفرع.

أودو (hr) تُنشئ جهة اتصال العمل بشركة الموظف، فإذا رُبطت سائقاً لمركبة
يملكها الأسطول صارت بطاقة المركبة غير قابلة للفتح من شركة الأسطول:
"سجلات سرية للغاية" على جهة الاتصال.

المعالجة تقتصر على جهات الاتصال **المرتبطة فعلاً بمركبة** (سائق حالي أو
مستقبلي) - لا تمسّ عملاء الفروع ولا مورّديها.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE res_partner
           SET company_id = NULL
         WHERE company_id IS NOT NULL
           AND id IN (
                SELECT driver_id FROM fleet_vehicle WHERE driver_id IS NOT NULL
                UNION
                SELECT future_driver_id FROM fleet_vehicle
                 WHERE future_driver_id IS NOT NULL
           )
    """)
    _logger.info('حُرِّرت %s جهة اتصال سائق من ملكية الفرع.', cr.rowcount)
