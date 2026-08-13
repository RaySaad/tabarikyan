# -*- coding: utf-8 -*-
from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _bank_settlement_fix_root_menu_parent(self):
        """يُعاد ربط قائمة "السداد البنكي" تحت تطبيق "المحاسبة" الحقيقي
        (Enterprise: موديول accountant) إن كان مثبتاً، بدل "الفوترة"
        الافتراضية (Community: account.menu_finance). تُستدعى من ملف بيانات
        XML (وليس post_init_hook فقط) لأنها تحتاج أن تعمل أيضاً عند
        الترقية (Upgrade) لموديول مثبَّت مسبقاً، وليس فقط عند التثبيت الأول.
        """
        accounting_root_menu = self.search([
            ('web_icon', '=like', 'accountant,%'),
            ('parent_id', '=', False),
        ], limit=1)
        if not accounting_root_menu:
            return
        bank_settlement_menu = self.env.ref(
            'bank_settlement.menu_bank_settlement_root', raise_if_not_found=False,
        )
        if bank_settlement_menu and bank_settlement_menu.parent_id != accounting_root_menu:
            bank_settlement_menu.parent_id = accounting_root_menu.id
        # "مستخدم/مراجع" السداد البنكي لا يملكون أي مجموعة محاسبية أصلية
        # (وليس مطلوباً منهم ذلك) - بدون هذا، لن يروا أيقونة "المحاسبة"
        # نفسها إطلاقاً حتى لو كانت لديهم صلاحية كاملة على قائمة "السداد
        # البنكي" المتفرعة تحتها، لأن جذر القائمة نفسه مقيَّد بمجموعة
        # محاسبية. نضيف مجموعتنا كخيار إضافي (لا نحذف/نستبدل الموجود) -
        # ما يرونه فعلياً بعد الدخول محصور بدوره عبر account_move_bank
        # _settlement_rule (ir.rule في security.xml).
        bank_settlement_user_group = self.env.ref(
            'bank_settlement.group_bank_settlement_user', raise_if_not_found=False,
        )
        if bank_settlement_user_group and bank_settlement_user_group not in accounting_root_menu.groups_id:
            accounting_root_menu.groups_id = [(4, bank_settlement_user_group.id)]
