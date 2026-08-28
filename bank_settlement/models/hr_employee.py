# -*- coding: utf-8 -*-
from datetime import date

from odoo import fields, models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = 'hr.employee'

    # توسيع صلاحية قراءة has_work_entries (حقل بولياني محسوب، لا بيانات
    # حساسة) لتشمل مستخدمي السداد البنكي أيضاً - كانت مقتصرة على
    # base.group_system/hr.group_hr_user فقط في hr_work_entry الأساسي.
    # نمنح group_bank_settlement_user وصول قراءة لسجل الموظف نفسه
    # (ضروري لعملهم)، وهذا التعارض بين صلاحية قراءة النموذج وصلاحية
    # قراءة هذا الحقل تحديداً كان يسبب تحذير "عدم اتساق في صلاحيات
    # الوصول" على زر "فتح إدخالات العمل" في نموذج الموظف (رغم أن الزر
    # نفسه محمي بـgroups=hr.group_hr_manager ولا يظهر لهم فعلياً - مجرد
    # تحذير استشاري، لكن إصلاحه الصحيح هو هذا بالضبط حسب توصية أودو
    # نفسها في رسالة التحذير).
    #
    # ملاحظة مهمة: هذا التوسيع يعتمد بالكامل على تحميل bank_settlement
    # *بعد* hr_work_entry (اعتماد صريح في __manifest__.py) - دمج خاصية
    # groups بين موديولات متعددة تُعيد تعريف نفس الحقل يحسمه ترتيب
    # التحميل فقط: آخر موديول يُحمَّل يفوز. بدون هذا الاعتماد الصريح، لا
    # يوجد ترتيب مضمون بين الموديولين، وإعادة تعريف hr_work_entry
    # الأصلي (الأضيق) قد تُلغي هذا التوسيع كلياً إن حُمِّل بعدنا - وهو ما
    # كان يحدث فعلياً (لا نُكرر compute= هنا عمداً: لا يُمسَح، يبقى من
    # التعريف الأصلي طالما لم نُعيّنه صراحة لقيمة أخرى).
    has_work_entries = fields.Boolean(
        groups='base.group_system,hr.group_hr_user,bank_settlement.group_bank_settlement_user',
    )

    # نفس حماية recruitment_workflow.hr_employee.unlink() بالضبط، لكن هنا
    # لنماذج bank_settlement تحديداً (سلفة/رسوم حكومية/تأمين طبي/تحويل
    # مركبة/تصفية مندوب) - موديول منفصل لا يعرفه recruitment_workflow،
    # فلا بد من فحص مستقل. سبّب غياب هذا الفحص فقدان بيانات فعلياً: حُذف
    # موظف له سلفة "بانتظار الموافقة" فتعطّلت الشاشة تماماً (الحقل إلزامي
    # في الواجهة لكن غير قابل للتعديل بعد مغادرة "مسودة").
    _BANK_SETTLEMENT_MODELS = [
        'bank.settlement.advance',
        'bank.settlement.government.fee',
        'bank.settlement.medical.insurance',
        'bank.settlement.vehicle.transfer',
        'bank.settlement.representative',
    ]

    def unlink(self):
        for employee in self:
            for model_name in self._BANK_SETTLEMENT_MODELS:
                if self.env[model_name].sudo().search_count(
                    [('employee_id', '=', employee.id)]
                ):
                    raise UserError(_(
                        'لا يمكن حذف الموظف "%s" نهائياً - له سجل/سجلات '
                        'سداد بنكي مرتبطة به (سلفة، رسوم حكومية، تأمين '
                        'طبي، تحويل مركبة، أو تصفية) يجب الحفاظ على '
                        'سجلها للتدقيق. استخدم "أرشفة" بدلاً من الحذف.'
                    ) % employee.name)
        return super().unlink()

    # -- كشف حساب الموظف (طباعة) -----------------------------------------
    # طلب صريح: كشف حساب موحّد يُعطى للموظف نفسه (بلا تقسيمات/مسميات
    # أقسام منفصلة، عمودا مدين/دائن، وإجمالي واحد فقط) - يقتصر على ما
    # "يخصه" فعلياً: سلف، تصفيات مناديب، مخالفات/رسوم رخصة مركبته
    # تحديداً، ورواتب/عمولات. الرسوم الحكومية والتأمين الطبي مستبعدان
    # عمداً (مصاريف داخلية للشركة، لا علاقة مباشرة للموظف بها من منظوره
    # هو). التصنيف مدين/دائن حسب تحديد صريح من المستخدم:
    # - سلفة: مدين (عليه - تُخصم من راتبه لاحقاً)
    # - تصفية مندوب: دائن (له - وصلته فعلاً)
    # - مخالفة مرور: مدين (عليه)
    # - رسوم رخصة قيادة: مدين (عليه - تُخصم منه)
    # - قيود حساب "ذمم الموظفين" (212003): كما هي مسجَّلة فعلاً في
    #   المحاسبة (مدين/دائن مباشرة من القيد نفسه، بلا إعادة تفسير)
    _VEHICLE_TRANSFER_STATEMENT_TYPES = (
        'bank_settlement.vehicle_transfer_type_traffic_violation',
        'bank_settlement.vehicle_transfer_type_driving_license',
    )

    def _get_employee_statement_data(self, date_from=False, date_to=False):
        """يبني كشف حساب موحّد (سطر واحد لكل حركة، مرتّب بالتاريخ) -
        انظر الشرح أعلاه لتصنيف مدين/دائن ولسبب استبعاد الرسوم الحكومية/
        التأمين الطبي عمداً.

        date_from/date_to اختياريان (طلب صريح: شاشة اختيار الموظف وتاريخ
        كشف الحساب - إما من بداية العقد أو تاريخ محدد - انظر
        bank.settlement.employee.statement.wizard التي تحسب/تمرر
        date_from فعلياً). بلا أي منهما تُعرَض كل الحركة التاريخية
        (السلوك الأصلي، محفوظ للتوافق الخلفي مع أي استدعاء مباشر)."""
        self.ensure_one()
        lines = []
        # كل الحسابات المحاسبية المرتبطة بسجلات السداد البنكي الخاصة بهذا
        # الموظف (بكل نماذجه الخمسة، حتى المستبعدة من العرض هنا كالرسوم
        # الحكومية) - تُستبعد صراحة من بحث حساب "ذمم الموظفين" أدناه،
        # بالإضافة لفلتر is_bank_settlement_move (وليس بديلاً عنه) - وإلا
        # أمكن ظهور نفس السلفة/التصفية مرتين لو اختار المحاسب حساب 212003
        # نفسه كـ"الحساب المرتبط" (linked_account_id) عند إتمامها؛ ثغرة
        # حقيقية اكتُشفت من كشف تجريبي حقيقي (سلفة "REQ/0001" ظهرت مرتين).
        bank_settlement_move_ids = set()
        for model_name in self._BANK_SETTLEMENT_MODELS:
            for rec in self.env[model_name].sudo().search(
                [('employee_id', '=', self.id), ('move_id', '!=', False)],
            ):
                bank_settlement_move_ids.add(rec.move_id.id)

        def _date_domain(field_name):
            domain = []
            if date_from:
                domain.append((field_name, '>=', date_from))
            if date_to:
                domain.append((field_name, '<=', date_to))
            return domain

        advances = self.env['bank.settlement.advance'].sudo().search(
            [('employee_id', '=', self.id)] + _date_domain('create_date'),
        )
        for adv in advances:
            lines.append({
                'date': adv.create_date.date(),
                'description': _('سلفة - %s') % (adv.advance_reason_id.name or adv.name),
                'debit': adv.amount,
                'credit': 0.0,
            })

        settlements = self.env['bank.settlement.representative'].sudo().search(
            [('employee_id', '=', self.id)] + _date_domain('date'),
        )
        for settlement in settlements:
            lines.append({
                'date': settlement.date,
                'description': _('تصفية مندوب - %s') % settlement.name,
                'debit': 0.0,
                'credit': settlement.settlement_amount,
            })

        statement_type_ids = [
            xmlid_id for xmlid_id in (
                self.env.ref(xmlid, raise_if_not_found=False).id
                for xmlid in self._VEHICLE_TRANSFER_STATEMENT_TYPES
            ) if xmlid_id
        ]
        vehicle_transfers = self.env['bank.settlement.vehicle.transfer'].sudo().search(
            [
                ('employee_id', '=', self.id),
                ('transfer_type_id', 'in', statement_type_ids),
            ] + _date_domain('create_date'),
        )
        for transfer in vehicle_transfers:
            lines.append({
                'date': transfer.create_date.date(),
                'description': '%s - %s' % (transfer.transfer_type_id.name, transfer.name),
                'debit': transfer.amount,
                'credit': 0.0,
            })

        # رواتب/عمولات وأي ذمم أخرى: قيود محاسبية مرحّلة على حساب "ذمم
        # الموظفين" تحديداً (كود 212003) - طلب صريح: هذا الحساب هو
        # المرجع الرسمي لكل ما يخص الموظف مالياً في دفاتر المحاسبة
        # الفعلية، فتُعرَض قيمة مدين/دائن لكل قيد كما هي مسجَّلة بالضبط
        # (بلا أي إعادة تفسير للاتجاه). باستثناء القيود التي أنشأها
        # السداد البنكي نفسه (is_bank_settlement_move) - وإلا تكرّرت نفس
        # السلفة/التصفية مرتين (مرة كسجل سداد بنكي، ومرة كقيد محاسبي).
        # work_contact_id تحديداً لتحديد قيود هذا الموظف بالذات ضمن نفس
        # الحساب المشترك لكل الموظفين - انظر أيضاً ثغرة سابقة مشابهة
        # اكتُشفت من كشف تجريبي حقيقي (فواتير غير مرتبطة بالموظف ظهرت
        # عند الاعتماد على سلسلة شريك احتياطية أوسع بدل هذا الحقل تحديداً).
        dues_account = self.env['account.account'].sudo().search(
            [('code', '=', '212003')], limit=1,
        )
        if not dues_account:
            dues_account = self.env['account.account'].sudo().search(
                [('name', 'ilike', 'ذمم الموظفين')], limit=1,
            )
        partner = self.sudo().work_contact_id
        # طلب صريح: يجب أن يفحص الكشف حتى القيود غير المرحّلة (لا يزال
        # مسودة) - وليس المرحّلة فقط - على حساب "ذمم الموظفين"، بنفس
        # مبدأ باقي أقسام الكشف أعلاه (سلفة/تصفية/مخالفة) التي أصلاً لا
        # تشترط أي حالة معينة. يُستبعد "ملغاة" فقط (cancel) - قيد أُلغي
        # فعلياً لا معنى لعرضه ضمن ذمم الموظف.
        dues_domain = [
            ('account_id', '=', dues_account.id if dues_account else False),
            ('partner_id', '=', partner.id if partner else False),
            ('move_id.is_bank_settlement_move', '=', False),
            ('move_id.state', '!=', 'cancel'),
        ] + _date_domain('date')
        if bank_settlement_move_ids:
            dues_domain.append(('move_id', 'not in', list(bank_settlement_move_ids)))
        dues_lines = self.env['account.move.line'].sudo().search(
            dues_domain,
        ) if (dues_account and partner) else self.env['account.move.line']
        for line in dues_lines:
            lines.append({
                'date': line.date,
                'description': line.name or line.move_id.ref or line.move_id.name,
                'debit': line.debit,
                'credit': line.credit,
            })

        lines.sort(key=lambda l: l['date'] or date.min)
        total_debit = sum(l['debit'] for l in lines)
        total_credit = sum(l['credit'] for l in lines)
        return {
            'lines': lines,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'net_total': total_credit - total_debit,
        }

