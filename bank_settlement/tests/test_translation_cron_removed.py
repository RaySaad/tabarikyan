# -*- coding: utf-8 -*-
"""لا مهمة مجدولة تدهس التسميات اليدوية.

كانت مهمة تعمل كل ساعة تُعيد استيراد ملفات .po بـforce_overwrite،
فتُرجع كل اسم مترجَم غيّره المستخدم (أنواع مرفقات التوظيف خصوصاً)
إلى أصله خلال ساعة.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTranslationCronRemoved(TransactionCase):

    def test_no_scheduled_job_force_reloads_translations(self):
        crons = self.env['ir.cron'].sudo().with_context(active_test=False).search([
            ('code', 'like', '_bank_settlement_force_load_en_translations'),
        ])
        self.assertFalse(
            crons,
            'مهمة فرض الترجمات ما زالت موجودة (%s) - ستُرجع التسميات اليدوية'
            % ', '.join(crons.mapped('name')))

    def test_the_manual_helper_is_still_available(self):
        """الدالة تبقى للاستدعاء اليدوي عند الحاجة - الممنوع جدولتها."""
        self.assertTrue(hasattr(
            self.env['ir.cron'], '_bank_settlement_force_load_en_translations'))
