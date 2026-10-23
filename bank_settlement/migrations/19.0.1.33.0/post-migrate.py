# -*- coding: utf-8 -*-
"""حفظ صلاحيات المستخدمين الحاليين عند تقسيم "مستخدم" إلى أقسام.

قبل هذه النسخة كانت مجموعة "مستخدم" تفتح الأقسام الخمسة. بعدها صارت
صلاحية كل قسم في مجموعته، فمن كان في "مستخدم" يفقد الأقسام كلها فجأةً
ويجد التطبيق فارغاً صباح الترقية.

فنمنح كل عضو حالي المجموعات الخمس: صلاحياته الفعلية تبقى كما هي حرفياً،
ثم يسحب المدير ما لا يلزم كلٌّ حسب عمله - وهو قرار إداري لا يصح أن
تتخذه ترقية.
"""
import logging

_logger = logging.getLogger(__name__)

_SECTION_GROUPS = (
    'bank_settlement.group_section_advance',
    'bank_settlement.group_section_government_fee',
    'bank_settlement.group_section_vehicle_transfer',
    'bank_settlement.group_section_medical_insurance',
    'bank_settlement.group_section_representative',
)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    base_group = env.ref('bank_settlement.group_bank_settlement_user',
                         raise_if_not_found=False)
    if not base_group:
        return

    # user_ids وحدها (لا all_user_ids): من ناله بالتضمين - كالمحاسب
    # والمدير - يأخذ الأقسام من تضمين مجموعته لا من هنا.
    users = base_group.user_ids
    if not users:
        _logger.info('لا مستخدمين في مجموعة "مستخدم" - لا شيء يُنقل.')
        return

    granted = 0
    for xmlid in _SECTION_GROUPS:
        group = env.ref(xmlid, raise_if_not_found=False)
        if not group:
            continue
        missing = users - group.all_user_ids
        if missing:
            group.write({'user_ids': [(4, user.id) for user in missing]})
            granted += len(missing)

    _logger.info(
        'قُسِّمت صلاحيات السداد: %s مستخدماً احتفظوا بأقسامهم (%s منح).',
        len(users), granted)
