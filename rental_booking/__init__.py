# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """يملأ عميلَي الحجز الافتراضيين على كل شركة قائمة.

    الحقلان على الشركة (لا xmlid ثابت في الكود) حتى تتمكن كل شركة من
    استخدام جهة اتصال أخرى - مكتب حجز مختلف مثلاً - دون تعديل الموديول.
    """
    cash = env.ref('rental_booking.partner_rental_cash', raise_if_not_found=False)
    gathern = env.ref('rental_booking.partner_rental_gathern', raise_if_not_found=False)
    for company in env['res.company'].sudo().search([]):
        vals = {}
        if cash and not company.rental_cash_partner_id:
            vals['rental_cash_partner_id'] = cash.id
        if gathern and not company.rental_platform_partner_id:
            vals['rental_platform_partner_id'] = gathern.id
        if vals:
            company.write(vals)
