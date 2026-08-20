# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BankSettlementSequenceResetWizard(models.TransientModel):
    """معالج إعادة ضبط الترقيم (ir.sequence) لأحد نماذج السداد البنكي -
    بديل داخل التطبيق نفسه عن الذهاب لشاشة "المتسلسلات" التقنية العامة
    (الإعدادات > التقنية > المتسلسلات والمعرّفات)، وليس آلية مختلفة -
    نفس الحقل (number_next_actual) بالضبط. أداة استثنائية بنفس مستوى
    حماية "الحذف النهائي الإداري" (مُغلَقة افتراضياً، صلاحية مدير عام
    السداد البنكي)، لأن إعادة الترقيم بلا حذف كل السجلات صاحبة الأرقام
    الحالية فعلياً تُنتج أكواداً مكرَّرة - خطر حقيقي إن استُخدمت بلا
    تأكد مسبق."""
    _name = 'bank.settlement.sequence.reset.wizard'
    _description = 'معالج إعادة ضبط ترقيم السداد البنكي'

    sequence_model = fields.Selection(
        selection=[
            ('bank.settlement.advance', 'السلف'),
            ('bank.settlement.government.fee', 'الرسوم الحكومية'),
            ('bank.settlement.vehicle.transfer', 'تحويلات المركبات'),
            ('bank.settlement.medical.insurance', 'التأمين الطبي'),
            ('bank.settlement.representative', 'تصفيات المناديب'),
        ],
        string='إعادة ترقيم', required=True,
    )
    next_number = fields.Integer(string='الرقم التالي', default=1, required=True)
    confirmation_text = fields.Char(
        string='اكتب "إعادة ترقيم" للتأكيد', required=True,
        help='تأكد أولاً أن كل السجلات صاحبة الأرقام الحالية أو '
             'الأعلى من الرقم الجديد قد حُذفت فعلاً - وإلا ستتكرر '
             'نفس الأكواد على سجلات مختلفة.',
    )
    _CONFIRMATION_TEXT = 'إعادة ترقيم'

    @api.model
    def _is_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'bank_settlement.admin_delete_enabled'
        ) in ('1', 'True', 'true')

    def action_confirm_reset(self):
        self.ensure_one()
        if not self._is_enabled():
            raise UserError(_(
                'ميزة "إعادة الترقيم" غير مُفعَّلة حالياً. فعِّلها من '
                'الإعدادات > التقنية > معاملات النظام '
                '(bank_settlement.admin_delete_enabled) قبل الاستخدام.'
            ))
        if not self.env.user.has_group('bank_settlement.group_bank_settlement_manager'):
            raise UserError(_('ليست لديك الصلاحية للقيام بهذا الإجراء.'))
        if (self.confirmation_text or '').strip() != self._CONFIRMATION_TEXT:
            raise UserError(_('يجب كتابة "%s" بالضبط للتأكيد.') % self._CONFIRMATION_TEXT)
        if self.next_number < 1:
            raise UserError(_('يجب أن يكون الرقم التالي 1 على الأقل.'))
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', self.sequence_model)], limit=1,
        )
        if not sequence:
            raise UserError(_('لا توجد متسلسلة مرتبطة بهذا النموذج.'))
        sequence.sudo().write({'number_next_actual': self.next_number})
        return {'type': 'ir.actions.act_window_close'}
