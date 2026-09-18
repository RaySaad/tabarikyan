# -*- coding: utf-8 -*-
import base64
import io
import re
import zipfile

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import human_size

# الضغط يجري كاملاً في ذاكرة الخادم، فحدٌّ للإجمالي يمنع تعليق الخادم
# على تحديد ضخم. تجاوزه خطأ واضح للمستخدم لا انتظار بلا نهاية.
MAX_TOTAL_BYTES = 200 * 1024 * 1024

# محارف لا تصلح في أسماء ملفات/مجلدات داخل الأرشيف (وبعضها ثغرة مسار).
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class PartnerAttachmentZip(models.TransientModel):
    _name = 'partner.attachment.zip'
    _description = 'تنزيل مرفقات جهات الاتصال'

    partner_ids = fields.Many2many('res.partner', string='جهات الاتصال', readonly=True)
    attachment_count = fields.Integer(string='عدد الملفات', readonly=True)
    total_size = fields.Char(string='الحجم', readonly=True)
    # attachment=False: يُحفظ المحتوى في عمود السجل المؤقت لا كمرفق دائم،
    # فيختفي مع تنظيف أودو للسجلات المؤقتة ولا يبقى في مخزن الملفات.
    file_data = fields.Binary(string='الملف المضغوط', readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        """يبني الأرشيف عند فتح النافذة: المستخدم يفتحها فيجد الملف جاهزاً."""
        res = super().default_get(fields_list)
        partners = self._active_partners()
        attachments = self._partner_attachments(partners)
        if not attachments:
            raise UserError(
                'لا توجد مرفقات على جهات الاتصال المحدَّدة.\n'
                'تذكّر أن المرفقات على جهات الاتصال التابعة (الأشخاص داخل '
                'الشركة) تخصّ سجلاتها هي - حدّدها معها إن أردتها.'
            )
        total = sum(attachments.mapped('file_size'))
        if total > MAX_TOTAL_BYTES:
            raise UserError(
                'إجمالي المرفقات %s وهو أكبر من الحد المسموح (%s) لعملية '
                'واحدة. حدّد عدداً أقل من جهات الاتصال ونزّلها على دفعات.'
                % (human_size(total), human_size(MAX_TOTAL_BYTES))
            )
        res.update({
            'partner_ids': [fields.Command.set(partners.ids)],
            'attachment_count': len(attachments),
            'total_size': human_size(total),
            'file_data': self._build_zip(partners, attachments),
            'file_name': self._zip_name(partners),
        })
        return res

    # ------------------------------------------------------------------
    @api.model
    def _active_partners(self):
        ctx = self.env.context
        if ctx.get('active_model') not in ('res.partner', False, None):
            raise UserError('هذا الإجراء يعمل على جهات الاتصال فقط.')
        partners = self.env['res.partner'].browse(ctx.get('active_ids') or [])
        if not partners:
            raise UserError('لم تُحدَّد أي جهة اتصال.')
        return partners.exists()

    @api.model
    def _partner_attachments(self, partners):
        """بصلاحيات المستخدم نفسه - بلا sudo: لا يُنزَّل ما لا يُرى.

        ونتخطى مرفقات نوع "رابط" فلا محتوى لها يُضغط."""
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', 'in', partners.ids),
            ('type', '=', 'binary'),
        ], order='res_id, id')

    @api.model
    def _safe_name(self, name, fallback):
        name = _UNSAFE.sub('_', (name or '')).strip(' .')
        return name or fallback

    @api.model
    def _unique_name(self, name, used):
        """أسماء متكرّرة داخل المجلد الواحد (شهادتان بالاسم نفسه) تُرقَّم،
        وإلا لابتلع الأرشيف إحداهما."""
        if name not in used:
            used.add(name)
            return name
        stem, dot, ext = name.rpartition('.')
        if not dot:
            stem, ext = name, ''
        counter = 2
        while True:
            candidate = '%s_%d%s%s' % (stem, counter, dot and '.' or '', ext)
            if candidate not in used:
                used.add(candidate)
                return candidate
            counter += 1

    @api.model
    def _build_zip(self, partners, attachments):
        by_partner = attachments.grouped('res_id')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for partner in partners:
                items = by_partner.get(partner.id)
                if not items:
                    continue
                folder = self._safe_name(partner.display_name, str(partner.id))
                used = set()
                for attachment in items:
                    raw = attachment.raw
                    if not raw:
                        continue
                    name = self._unique_name(
                        self._safe_name(attachment.name, 'ملف_%d' % attachment.id),
                        used,
                    )
                    archive.writestr('%s/%s' % (folder, name), raw)
        # حقول Binary في أودو تُخزَّن وتُقرأ بترميز base64.
        return base64.b64encode(stream.getvalue())

    @api.model
    def _zip_name(self, partners):
        # وقت المستخدم لا UTC، وبأرقام لاتينية دائماً - اسم ملف لا نص معروض.
        stamp = fields.Datetime.context_timestamp(
            self.env.user, fields.Datetime.now()).strftime('%Y%m%d_%H%M')
        if len(partners) == 1:
            return '%s_%s.zip' % (
                self._safe_name(partners.display_name, 'مرفقات'), stamp)
        return 'مرفقات_جهات_الاتصال_%s.zip' % stamp
