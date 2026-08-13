# -*- coding: utf-8 -*-


def _post_init_hook(env):
    """يُعاد ربط قائمة "السداد البنكي" تلقائياً تحت تطبيق "المحاسبة" الحقيقي
    (Enterprise، موديول accountant) إن كان مثبتاً، بدل تطبيق "الفوترة"
    الأساسي (Community، account.menu_finance) المستخدم كاحتياط افتراضي في
    XML. نبحث عن القائمة الجذرية للمحاسبة بأيقونتها المميزة بدل الاعتماد
    على معرّف XML ثابت قد يختلف بين إصدارات أودو - أكثر أماناً من تعليق
    تثبيت الموديول بالكامل لو كان المعرّف غير صحيح.
    """
    accounting_root_menu = env['ir.ui.menu'].search([
        ('web_icon', 'like', 'accountant,%'),
        ('parent_id', '=', False),
    ], limit=1)
    if not accounting_root_menu:
        return
    bank_settlement_menu = env.ref(
        'bank_settlement.menu_bank_settlement_root', raise_if_not_found=False,
    )
    if bank_settlement_menu:
        bank_settlement_menu.parent_id = accounting_root_menu.id
    # "مستخدم/مراجع" السداد البنكي لا يملكون أي مجموعة محاسبية أصلية -
    # بدون هذا لن يروا أيقونة "المحاسبة" نفسها إطلاقاً (انظر نفس الشرح
    # في ir_ui_menu.py._bank_settlement_fix_root_menu_parent).
    bank_settlement_user_group = env.ref(
        'bank_settlement.group_bank_settlement_user', raise_if_not_found=False,
    )
    if bank_settlement_user_group and bank_settlement_user_group not in accounting_root_menu.group_ids:
        accounting_root_menu.group_ids = [(4, bank_settlement_user_group.id)]
