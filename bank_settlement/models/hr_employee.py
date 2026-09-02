# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = 'hr.employee'

    def _get_platform_analytic_distribution(self, on_date):
        """يبحث في تاريخ منصات المندوب (platform_history_ids من
        recruitment_workflow) عن الفترة التي تغطي on_date تحديداً، ويُعيد
        توزيعاً تحليلياً 100% على حساب تلك المنصة - أو False إن لم توجد
        فترة تغطي هذا التاريخ (موظف لم يُسنَد بعد لأي منصة، أو تاريخ
        خارج أي فترة مسجَّلة) فيبقى القيد بلا تصنيف تحليلي بدل إيقاف
        الإنشاء بالكامل. تُستخدَم من account_asset.py._prepare_move."""
        self.ensure_one()
        history = self.sudo().platform_history_ids.filtered(
            lambda h: h.date_start <= on_date and (not h.date_end or h.date_end >= on_date)
        )
        account = history[:1].project_id.account_id
        return {str(account.id): 100} if account else False

    def _open_platform_history(self, project, note=False, date_start=None):
        """تمديد: بعد تنفيذ نقل المنصة الفعلي كالمعتاد (يُغلق الفترة
        القديمة ويفتح الجديدة - بلا أي تغيير على ذلك السلوك)، نسوّي فوراً
        أي جزء "منقضٍ" من دفعة مقدمة قيد السريان له - انظر
        _settle_prepaid_lines_on_transfer للتفاصيل الكاملة."""
        self.ensure_one()
        old_open = self.sudo().platform_history_ids.filtered(lambda h: not h.date_end)
        old_project = old_open[:1].project_id
        result = super()._open_platform_history(project, note=note, date_start=date_start)
        if old_project and old_project != project:
            transfer_date = date_start or fields.Date.context_today(self)
            self._settle_prepaid_lines_on_transfer(transfer_date)
        return result

    def _settle_prepaid_lines_on_transfer(self, transfer_date):
        """عند نقل منصة فعلي، تُسوَّى فوراً (بلا مراجعة بشرية - طلب
        صريح) أي فترة استهلاك "دفعة مقدمة" لم تُرحَّل بعد وتغطي تاريخ
        النقل: الجزء المنقضي حتى اليوم السابق للنقل (بنسبة الأيام
        الفعلية من الفترة) يُنشأ له قيد فوري منفصل ويُرحَّل مباشرة -
        تلقائياً يأخذ توزيع المنصة *القديمة* لأن تاريخه يقع ضمن فترتها
        (انظر account_asset.py._prepare_move: يبحث بتاريخ القيد نفسه).
        الجزء المتبقي يبقى كسطر واحد بنفس السطر الأصلي (فقط مبلغه
        يُخفَّض)، يتبع المنصة الجديدة تلقائياً بنفس الآلية عند استحقاقه
        لاحقاً - دون أي حاجة لإنشاء سطر جديد له أو التدخل يدوياً."""
        self.ensure_one()
        Line = self.env['account.asset.depreciation.line'].sudo()
        open_lines = Line.search([
            ('asset_id.employee_id', '=', self.id),
            ('asset_id.state', '=', 'open'),
            ('move_id', '=', False),
            ('period_start_date', '<=', transfer_date),
            ('depreciation_date', '>=', transfer_date),
        ])
        currency_decimals = self.env.company.currency_id.decimal_places
        for line in open_lines:
            period_start = line.period_start_date
            period_end = line.depreciation_date
            total_days = (period_end - period_start).days + 1
            elapsed_days = (transfer_date - period_start).days
            if elapsed_days <= 0 or total_days <= 0:
                continue
            elapsed_amount = round(line.amount * elapsed_days / total_days, currency_decimals)
            remaining_amount = line.amount - elapsed_amount
            if not remaining_amount:
                continue
            settle_line = line.copy({
                'amount': elapsed_amount,
                'depreciation_date': transfer_date - timedelta(days=1),
                'period_start_date': period_start,
                'name': _('%s - تسوية نقل منصة') % line.name,
            })
            settle_line.create_move()
            line.write({
                'amount': remaining_amount,
                'period_start_date': transfer_date,
            })

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

