# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BankSettlementRenameWizard(models.TransientModel):
    """معالج "تعديل الكود الإداري" - أداة استثنائية (مُغلَقة افتراضياً،
    تستخدم نفس مفتاح bank_settlement_mixin._is_admin_delete_enabled الذي
    يفعّل الحذف النهائي الإداري وإعادة ضبط الترقيم) لتصحيح فجوة/ترتيب في
    أكواد عدة سجلات موجودة فعلاً دفعة واحدة - وليس سجلاً سجلاً (طلب صريح:
    تصحيح كل الفجوة/الترتيب مرة واحدة، لا فتح كل سلفة على حدة).

    تُفتح من قائمة "الإجراءات" (⚙) بعد تحديد عدة سجلات من شاشة القائمة
    (مثلاً السلف) - نفس آلية hr.employee.platform.bulk.assign.wizard
    بالضبط (binding_model_id + binding_view_types='list')."""
    _name = 'bank.settlement.rename.wizard'
    _description = 'معالج تعديل الكود الإداري - سداد بنكي'

    line_ids = fields.One2many(
        'bank.settlement.rename.wizard.line', 'wizard_id', string='السجلات',
    )
    line_count = fields.Integer(string='عدد السجلات', compute='_compute_line_count')
    start_number = fields.Integer(
        string='يبدأ الترقيم من', default=1,
        help='يُستخدم مع زر "ترقيم تلقائي متسلسل" فقط - الرقم الذي يبدأ '
             'منه السجل الأقدم بين المحدَّدين، وتُرقَّم الباقي تباعاً بلا '
             'أي فجوة (بنفس بادئة/تنسيق الكود المعتاد لهذا النموذج).',
    )
    reason = fields.Text(string='سبب التعديل', required=True)
    confirmation_text = fields.Char(
        string='اكتب "تعديل الكود" للتأكيد', required=True,
        help='طبقة تأكيد إضافية - تعديل الكود بعد اعتماده/تنفيذه فعلياً '
             'يجب أن يكون استثناءً واعياً، وليس تعديلاً عابراً.',
    )
    _CONFIRMATION_TEXT = 'تعديل الكود'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            res_model = self.env.context.get('active_model')
            res_ids = self.env.context.get('active_ids')
            if res_model and res_ids:
                records = self.env[res_model].browse(res_ids)
                res['line_ids'] = [
                    (0, 0, {
                        'res_model': res_model,
                        'res_id': record.id,
                        'old_code': record.name,
                        'new_code': record.name,
                    })
                    for record in records
                ]
        return res

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_auto_sequence(self):
        """يملأ "الكود الجديد" تلقائياً لكل الأسطر - ترقيم متسلسل بلا أي
        فجوة، بترتيب res_id (ترتيب الإنشاء الفعلي، وليس الكود الحالي نفسه
        الذي قد يكون غير مرتَّب أصلاً وهو بالضبط المشكلة المطلوب تصحيحها).
        يستخدم نفس بادئة/تنسيق ir.sequence المعرَّف لهذا النموذج (نفس
        القيم المستخدمة في sequence_reset_wizard) - فالنتيجة أكواد بنفس
        الشكل المعتاد تماماً، فقط بلا فجوات. لا يُنفَّذ أي تعديل فعلي بعد -
        يبقى للمستخدم مراجعة الجدول قبل الضغط على "تأكيد تعديل الأكواد"."""
        self.ensure_one()
        by_model = {}
        for line in self.line_ids:
            by_model.setdefault(line.res_model, []).append(line)
        for res_model, lines in by_model.items():
            sequence = self.env['ir.sequence'].sudo().search(
                [('code', '=', res_model)], limit=1,
            )
            if not sequence:
                continue
            prefix = sequence.prefix or ''
            padding = sequence.padding or 0
            lines.sort(key=lambda l: l.res_id)
            for index, line in enumerate(lines):
                number = self.start_number + index
                line.new_code = '%s%s' % (prefix, str(number).zfill(padding))

    def action_confirm_rename(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('لم يتم تحديد أي سجل.'))
        if not self.reason:
            raise UserError(_('يجب توضيح سبب تعديل الكود.'))
        if (self.confirmation_text or '').strip() != self._CONFIRMATION_TEXT:
            raise UserError(_('يجب كتابة "%s" بالضبط للتأكيد.') % self._CONFIRMATION_TEXT)
        # فحص تكرار الأكواد الجديدة داخل الدفعة نفسها أولاً - قبل أي تعديل
        # فعلي، حتى لا ننفّذ نصف الدفعة ثم نكتشف تعارضاً في نصفها الآخر.
        seen = {}
        for line in self.line_ids:
            new_code = (line.new_code or '').strip()
            if not new_code:
                raise UserError(_('يوجد سطر بلا كود جديد - أكمله أو احذف السطر.'))
            if new_code in seen and seen[new_code] != line.old_code:
                raise UserError(_(
                    'الكود "%s" مكرَّر أكثر من مرة ضمن نفس الدفعة.'
                ) % new_code)
            seen[new_code] = line.old_code
        for line in self.line_ids:
            new_code = (line.new_code or '').strip()
            if new_code == line.old_code:
                continue
            record = self.env[line.res_model].browse(line.res_id)
            record.action_admin_rename(new_code=new_code, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}


class BankSettlementRenameWizardLine(models.TransientModel):
    _name = 'bank.settlement.rename.wizard.line'
    _description = 'سطر تعديل كود (معالج التعديل الجماعي)'

    wizard_id = fields.Many2one(
        'bank.settlement.rename.wizard', required=True, ondelete='cascade',
    )
    res_model = fields.Char(string='النموذج', required=True)
    res_id = fields.Integer(string='رقم السجل', required=True)
    old_code = fields.Char(string='الكود الحالي', readonly=True)
    new_code = fields.Char(string='الكود الجديد', required=True)
