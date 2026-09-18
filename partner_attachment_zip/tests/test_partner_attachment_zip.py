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
