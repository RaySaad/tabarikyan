# -*- coding: utf-8 -*-
import base64
import io
import zipfile

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPartnerAttachmentZip(TransactionCase):
    """تنزيل مرفقات جهات الاتصال في ملف مضغوط واحد."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_partner = cls.env['res.partner'].create({
            'name': 'شركة اليمنترا', 'is_company': True})
        cls.other_partner = cls.env['res.partner'].create({'name': 'مورد آخر'})

    def _attach(self, partner, name, content=b'PDF-DATA', **vals):
        return self.env['ir.attachment'].create(dict({
            'name': name,
            'datas': base64.b64encode(content),
            'res_model': 'res.partner',
            'res_id': partner.id,
        }, **vals))

    def _zip(self, partners):
        wizard = self.env['partner.attachment.zip'].with_context(
            active_model='res.partner', active_ids=partners.ids,
        ).create({})
        return wizard, zipfile.ZipFile(
            io.BytesIO(base64.b64decode(wizard.file_data)))

    # ---- المحتوى ----
    def test_zip_holds_every_attachment_in_a_folder_per_contact(self):
        self._attach(self.company_partner, 'شهادة الضريبة.pdf', b'VAT')
        self._attach(self.company_partner, 'عنوان وطني.pdf', b'ADDR')
        self._attach(self.other_partner, 'عقد.pdf', b'CONTRACT')

        wizard, archive = self._zip(self.company_partner | self.other_partner)

        self.assertEqual(wizard.attachment_count, 3)
        self.assertEqual(sorted(archive.namelist()), sorted([
            'شركة اليمنترا/شهادة الضريبة.pdf',
            'شركة اليمنترا/عنوان وطني.pdf',
            'مورد آخر/عقد.pdf',
        ]))
        self.assertEqual(archive.read('مورد آخر/عقد.pdf'), b'CONTRACT')

    def test_other_contacts_attachments_are_not_included(self):
        """لا يخرج من الأرشيف إلا مرفقات ما حدَّده المستخدم."""
        self._attach(self.company_partner, 'لنا.pdf')
        self._attach(self.other_partner, 'ليس لنا.pdf')

        _wizard, archive = self._zip(self.company_partner)

        self.assertEqual(archive.namelist(), ['شركة اليمنترا/لنا.pdf'])

    def test_repeated_file_names_are_both_kept(self):
        """ملفان بالاسم نفسه على الجهة ذاتها - الترقيم يمنع ابتلاع أحدهما."""
        self._attach(self.company_partner, 'صورة.pdf', b'ONE')
        self._attach(self.company_partner, 'صورة.pdf', b'TWO')

        _wizard, archive = self._zip(self.company_partner)

        self.assertEqual(sorted(archive.namelist()), sorted([
            'شركة اليمنترا/صورة.pdf', 'شركة اليمنترا/صورة_2.pdf']))

    def test_slash_in_a_contact_name_does_not_create_folders(self):
        """اسم فيه شرطة مائلة كان سيولّد مساراً داخل الأرشيف."""
        partner = self.env['res.partner'].create({'name': 'مؤسسة أ/ب'})
        self._attach(partner, 'ملف.pdf')

        _wizard, archive = self._zip(partner)

        self.assertEqual(archive.namelist(), ['مؤسسة أ_ب/ملف.pdf'])

    def test_url_attachments_are_skipped(self):
        """مرفق من نوع رابط لا محتوى له يُضغط."""
        self._attach(self.company_partner, 'ملف حقيقي.pdf')
        self.env['ir.attachment'].create({
            'name': 'رابط خارجي', 'type': 'url', 'url': 'https://example.com/x.pdf',
            'res_model': 'res.partner', 'res_id': self.company_partner.id})

        wizard, archive = self._zip(self.company_partner)

        self.assertEqual(wizard.attachment_count, 1)
        self.assertEqual(archive.namelist(), ['شركة اليمنترا/ملف حقيقي.pdf'])

    # ---- الحدود ----
    def test_contacts_without_attachments_raise_a_clear_error(self):
        with self.assertRaises(UserError):
            self._zip(self.other_partner)

    def test_nothing_selected_raises(self):
        with self.assertRaises(UserError):
            self.env['partner.attachment.zip'].with_context(
                active_model='res.partner', active_ids=[]).create({})

    def test_a_huge_selection_is_refused_instead_of_hanging(self):
        """الضغط في الذاكرة: تحديد ضخم يُرفض برسالة بدل تعليق الخادم.

        نزوّر الحجم في قاعدة البيانات بدل رفع ٣٠٠ ميغا فعلية."""
        huge = self._attach(self.company_partner, 'ضخم.pdf')
        huge.flush_recordset()
        self.env.cr.execute(
            'UPDATE ir_attachment SET file_size = %s WHERE id = %s',
            (300 * 1024 * 1024, huge.id))
        huge.invalidate_recordset(['file_size'])
        with self.assertRaises(UserError):
            self._zip(self.company_partner)

    # ---- اسم الملف ----
    def test_single_contact_zip_is_named_after_it(self):
        self._attach(self.company_partner, 'ملف.pdf')
        wizard, _archive = self._zip(self.company_partner)
        self.assertTrue(wizard.file_name.startswith('شركة اليمنترا_'))
        self.assertTrue(wizard.file_name.endswith('.zip'))

    # ---- فتح النافذة ----
    def test_action_opens_a_saved_record(self):
        """السجل غير المحفوظ لا يعطي حقل الملف رابط تنزيل - فلا بد أن
        ينشئه الإجراء أولاً ويفتح النافذة عليه."""
        self._attach(self.company_partner, 'ملف.pdf')

        action = self.env['partner.attachment.zip'].with_context(
            active_model='res.partner', active_ids=self.company_partner.ids,
        ).action_prepare()

        self.assertEqual(action['res_model'], 'partner.attachment.zip')
        self.assertTrue(action.get('res_id'), 'النافذة تُفتح بلا سجل محفوظ')
        wizard = self.env['partner.attachment.zip'].browse(action['res_id'])
        self.assertTrue(wizard.exists())
        self.assertTrue(wizard.file_data)

    def test_download_button_points_at_the_saved_file(self):
        self._attach(self.company_partner, 'ملف.pdf')
        wizard = self.env['partner.attachment.zip'].with_context(
            active_model='res.partner', active_ids=self.company_partner.ids,
        ).create({})

        action = wizard.action_download()

        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/partner.attachment.zip/%s/file_data/' % wizard.id,
                      action['url'])
        self.assertIn('download=true', action['url'])


@tagged('post_install', '-at_install')
class TestPartnerAttachmentZipStream(TransactionCase):
    """مسار التنزيل نفسه الذي يسلكه /web/content: إيجاد السجل، فحص
    الصلاحية، ثم تحويل الحقل إلى ملف باسمه.

    (بقية المسار - بناء الاستجابة - يتطلب طلب HTTP حقيقياً، فلا يُختبر
    هنا؛ جُرّب الرابط على خادم حي فأعاد 200 و application/zip.)"""

    def test_the_download_url_resolves_to_the_zip(self):
        partner = self.env['res.partner'].create({'name': 'شركة التنزيل'})
        self.env['ir.attachment'].create({
            'name': 'شهادة.pdf', 'raw': b'PDF-DATA',
            'res_model': 'res.partner', 'res_id': partner.id})
        wizard = self.env['partner.attachment.zip'].with_context(
            active_model='res.partner', active_ids=partner.ids).create({})

        # ما يفعله /web/content أولاً: يجد السجل ويفحص صلاحية القراءة.
        record = self.env['ir.binary']._find_record(
            res_model='partner.attachment.zip', res_id=wizard.id, field='file_data')

        self.assertEqual(record, wizard)
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(record.file_data)))
        self.assertEqual(archive.namelist(), ['شركة التنزيل/شهادة.pdf'])
        self.assertEqual(archive.read('شركة التنزيل/شهادة.pdf'), b'PDF-DATA')


@tagged('post_install', '-at_install')
class TestPartnerAttachmentZipBinding(TransactionCase):
    """الربط بشاشة جهات الاتصال - وإلا لا يظهر الإجراء أصلاً."""

    def test_action_is_bound_to_contacts(self):
        action = self.env.ref(
            'partner_attachment_zip.action_partner_attachment_zip_server')
        self.assertEqual(action.binding_model_id.model, 'res.partner')
        self.assertEqual(action.binding_view_types, 'list,form')

    def test_the_old_act_window_id_is_gone(self):
        """المعرّف القديم استُبدل بإجراء خادم تحت معرّف آخر؛ بقاؤه يعني
        ظهور إجراءين في القائمة أحدهما معطوب."""
        self.assertFalse(self.env.ref(
            'partner_attachment_zip.action_partner_attachment_zip',
            raise_if_not_found=False))
