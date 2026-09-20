# -*- coding: utf-8 -*-
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BankSettlementDashboard(models.AbstractModel):
    """نموذج تجميع البيانات والإحصائيات للوحة مؤشرات السداد البنكي (Bank Settlement Dashboard)."""
    _name = 'bank.settlement.dashboard'
    _description = 'لوحة مؤشرات السداد البنكي'

    @api.model
    def _get_period_date_range(self, period):
        """يحسب تاريخ البداية والنهاية للفترة المختارة وفترة المقارنة السابقة لها."""
        today = fields.Date.context_today(self)
        current_start = None
        current_end = None
        prev_start = None
        prev_end = None

        if period == 'today':
            current_start = today
            current_end = today
            prev_start = today - timedelta(days=1)
            prev_end = prev_start

        elif period == 'this_week':
            # بداية الأسبوع: نبدأ من السبت
            day_of_week = today.weekday()
            days_from_saturday = (day_of_week + 2) % 7
            current_start = today - timedelta(days=days_from_saturday)
            current_end = current_start + timedelta(days=6)
            prev_start = current_start - timedelta(days=7)
            prev_end = current_start - timedelta(days=1)

        elif period == 'this_month':
            current_start = today.replace(day=1)
            dummy_first, last_day = calendar.monthrange(today.year, today.month)
            current_end = today.replace(day=last_day)
            # الشهر السابق
            first_of_last_month = current_start - relativedelta(months=1)
            dummy_first_p, prev_last_day = calendar.monthrange(first_of_last_month.year, first_of_last_month.month)
            prev_start = first_of_last_month
            prev_end = first_of_last_month.replace(day=prev_last_day)

        elif period == 'last_month':
            first_of_last_month = today.replace(day=1) - relativedelta(months=1)
            dummy_first_p, prev_last_day = calendar.monthrange(first_of_last_month.year, first_of_last_month.month)
            current_start = first_of_last_month
            current_end = first_of_last_month.replace(day=prev_last_day)
            # شهران سابقان للمقارنة
            two_months_ago = current_start - relativedelta(months=1)
            dummy_first_2, two_last_day = calendar.monthrange(two_months_ago.year, two_months_ago.month)
            prev_start = two_months_ago
            prev_end = two_months_ago.replace(day=two_last_day)

        elif period == 'this_year':
            current_start = today.replace(month=1, day=1)
            current_end = today.replace(month=12, day=31)
            prev_start = current_start - relativedelta(years=1)
            prev_end = current_end - relativedelta(years=1)

        elif period == 'all':
            current_start = None
            current_end = None
            prev_start = None
            prev_end = None

        return current_start, current_end, prev_start, prev_end

    @api.model
    def get_dashboard_data(self, period='this_month', project_id=False):
        """
        تجميع كافة بيانات لوحة المؤشرات:
        - بطاقات الأداء المالي (KPIs)
        - مركز الموافقات والإجراءات المعلقة (Action Center)
        - الرسوم البيانية التفاعلية (Chart.js)
        - التنبيهات الذكية
        - سجل أحدث العمليات
        """
        company_ids = self.env.companies.ids
        current_start, current_end, prev_start, prev_end = self._get_period_date_range(period)

        # تحويل project_id لرقم صحيح ومطابقة كافة المشاريع ذات نفس اسم المنصة عبر الشركات النشطة
        proj_id = int(project_id) if project_id else False
        matching_project_ids = []
        if proj_id:
            target_project = self.env['project.project'].sudo().browse(proj_id)
            if target_project.exists():
                target_name = (target_project.name or '').strip()
                matching_projects = self.env['project.project'].sudo().search([
                    '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
                    ('name', '=ilike', target_name),
                ])
                matching_project_ids = matching_projects.ids
            if not matching_project_ids:
                matching_project_ids = [proj_id]

        # عملة الشركة الأساسية
        currency = self.env.company.currency_id
        currency_data = {
            'symbol': currency.symbol or 'ر.س',
            'position': currency.position or 'after',
            'decimals': currency.decimal_places or 2,
        }

        # 1. حساب مبالغ وأعداد العمليات المنجزة (Settled / Paid)
        def _get_settled_stats(model_name, done_state='done', amount_field='amount', date_field='transfer_date'):
            base_domain = [
                '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
                ('state', '=', done_state)
            ]
            if matching_project_ids:
                base_domain.append(('project_id', 'in', matching_project_ids))

            # الفترة الحالية
            curr_domain = list(base_domain)
            if current_start and current_end:
                curr_domain.extend([
                    '|',
                    '&', (date_field, '>=', current_start), (date_field, '<=', current_end),
                    '&', (date_field, '=', False), ('create_date', '>=', f'{current_start} 00:00:00'), ('create_date', '<=', f'{current_end} 23:59:59')
                ])

            records = self.env[model_name].sudo().search(curr_domain)
            total_amt = sum(records.mapped(amount_field))
            count = len(records)

            # الفترة السابقة للمقارنة
            prev_total_amt = 0.0
            if prev_start and prev_end:
                prev_domain = list(base_domain)
                prev_domain.extend([
                    '|',
                    '&', (date_field, '>=', prev_start), (date_field, '<=', prev_end),
                    '&', (date_field, '=', False), ('create_date', '>=', f'{prev_start} 00:00:00'), ('create_date', '<=', f'{prev_end} 23:59:59')
                ])
                prev_records = self.env[model_name].sudo().search(prev_domain)
                prev_total_amt = sum(prev_records.mapped(amount_field))

            return total_amt, count, prev_total_amt

        # إحصائيات كل نموذج من النماذج الخمسة
        adv_amt, adv_count, adv_prev = _get_settled_stats('bank.settlement.advance', 'paid', 'amount', 'transfer_date')
        gov_amt, gov_count, gov_prev = _get_settled_stats('bank.settlement.government.fee', 'done', 'total_amount', 'transfer_date')
        veh_amt, veh_count, veh_prev = _get_settled_stats('bank.settlement.vehicle.transfer', 'done', 'amount', 'transfer_date')
        med_amt, med_count, med_prev = _get_settled_stats('bank.settlement.medical.insurance', 'done', 'amount', 'transfer_date')
        rep_amt, rep_count, rep_prev = _get_settled_stats('bank.settlement.representative', 'done', 'amount', 'date')

        # إجمالي المبالغ المنفذة
        total_settled_amt = adv_amt + gov_amt + veh_amt + med_amt + rep_amt
        total_settled_count = adv_count + gov_count + veh_count + med_count + rep_count
        total_prev_amt = adv_prev + gov_prev + veh_prev + med_prev + rep_prev

        # نسبة التغير مقارنة بالفترة السابقة
        growth_rate = 0.0
        if total_prev_amt > 0:
            growth_rate = round(((total_settled_amt - total_prev_amt) / total_prev_amt) * 100, 1)
        elif total_settled_amt > 0 and total_prev_amt == 0:
            growth_rate = 100.0

        # 2. مركز الموافقات والإجراءات المعلقة (Approvals Pipeline)
        def _get_pending_stats(model_name, state_value, amount_field='amount'):
            domain = [
                '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
                ('state', '=', state_value)
            ]
            if matching_project_ids:
                domain.append(('project_id', 'in', matching_project_ids))
            recs = self.env[model_name].sudo().search(domain)
            return len(recs), sum(recs.mapped(amount_field))

        # السلف: ثلاث مراحل حيوية للموافقات
        adv_wait_pm_count, adv_wait_pm_amt = _get_pending_stats('bank.settlement.advance', 'waiting_approval', 'amount')
        adv_wait_gm_count, adv_wait_gm_amt = _get_pending_stats('bank.settlement.advance', 'pm_approved', 'amount')
        adv_appr_unpaid_count, adv_appr_unpaid_amt = _get_pending_stats('bank.settlement.advance', 'approved', 'amount')

        # بقية النماذج: مرحلة تحت المراجعة (under_review)
        gov_review_count, gov_review_amt = _get_pending_stats('bank.settlement.government.fee', 'under_review', 'total_amount')
        veh_review_count, veh_review_amt = _get_pending_stats('bank.settlement.vehicle.transfer', 'under_review', 'amount')
        med_review_count, med_review_amt = _get_pending_stats('bank.settlement.medical.insurance', 'under_review', 'amount')
        rep_review_count, rep_review_amt = _get_pending_stats('bank.settlement.representative', 'under_review', 'amount')

        # سجلات أُرجعت للتصحيح عبر كل النماذج
        ret_domain = [
            '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
            ('returned_for_correction', '=', True)
        ]
        if matching_project_ids:
            ret_domain.append(('project_id', 'in', matching_project_ids))
        returned_count = (
            self.env['bank.settlement.advance'].sudo().search_count(ret_domain) +
            self.env['bank.settlement.government.fee'].sudo().search_count(ret_domain) +
            self.env['bank.settlement.vehicle.transfer'].sudo().search_count(ret_domain) +
            self.env['bank.settlement.medical.insurance'].sudo().search_count(ret_domain) +
            self.env['bank.settlement.representative'].sudo().search_count(ret_domain)
        )

        # 3. التنبيهات: أسطر الدفعات المقدمة المستحقة للترحيل الآن
        today = fields.Date.context_today(self)
        prepaid_domain = [
            '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
            ('state', '=', 'draft'),
            ('period_end_date', '<=', today),
        ]
        if matching_project_ids:
            prepaid_domain.append(('employee_id.project_id', 'in', matching_project_ids))
        due_prepaid_recs = self.env['bank.settlement.prepaid.line'].sudo().search(prepaid_domain)
        due_prepaid_count = len(due_prepaid_recs)
        due_prepaid_amt = sum(due_prepaid_recs.mapped('amount'))

        # 4. الرسوم البيانية التفاعلية (Charts Data)

        # أ. توزيع التكاليف حسب المنصة (Platform Breakdown)
        # الرسم الدائري يعرض التوزيع الشامل لكافة المنصات عبر الشركات النشطة دائماً دون حجب باقي المشاريع
        platform_dict = {}
        models_config = [
            ('bank.settlement.advance', 'paid', 'amount', 'transfer_date'),
            ('bank.settlement.government.fee', 'done', 'total_amount', 'transfer_date'),
            ('bank.settlement.vehicle.transfer', 'done', 'amount', 'transfer_date'),
            ('bank.settlement.medical.insurance', 'done', 'amount', 'transfer_date'),
            ('bank.settlement.representative', 'done', 'amount', 'date'),
        ]
        for m_name, d_state, a_field, d_field in models_config:
            d = [
                '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
                ('state', '=', d_state)
            ]
            if current_start and current_end:
                d.extend([
                    '|',
                    '&', (d_field, '>=', current_start), (d_field, '<=', current_end),
                    '&', (d_field, '=', False), ('create_date', '>=', f'{current_start} 00:00:00'), ('create_date', '<=', f'{current_end} 23:59:59')
                ])
            grouped = self.env[m_name].sudo()._read_group(d, groupby=['project_id'], aggregates=[f'{a_field}:sum'])
            for proj_rec, amt in grouped:
                proj_name = (proj_rec.name or '').strip() if proj_rec else _('بدون منصة محددة')
                platform_dict[proj_name] = platform_dict.get(proj_name, 0.0) + (amt or 0.0)

        platform_labels = list(platform_dict.keys())
        platform_data = [round(v, 2) for v in platform_dict.values()]

        # ب. توزيع المصروفات حسب نوع العملية (Category Breakdown)
        category_labels = [_('السلف'), _('الرسوم الحكومية'), _('تحويلات المركبات'), _('التأمين الطبي'), _('تصفيات المناديب')]
        category_data = [round(adv_amt, 2), round(gov_amt, 2), round(veh_amt, 2), round(med_amt, 2), round(rep_amt, 2)]

        # ج. الاتجاه الشهري للمصروفات لآخر 6 أشهر (Monthly Trend - Last 6 Months)
        monthly_trend_labels = []
        monthly_trend_adv = []
        monthly_trend_gov = []
        monthly_trend_veh = []
        monthly_trend_med = []
        monthly_trend_rep = []

        months_list = []
        first_current = today.replace(day=1)
        for i in range(5, -1, -1):
            m_date = first_current - relativedelta(months=i)
            dummy_m, m_last_day = calendar.monthrange(m_date.year, m_date.month)
            m_start = m_date
            m_end = m_date.replace(day=m_last_day)
            month_names_ar = ['', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
            label_text = f"{month_names_ar[m_date.month]} {m_date.year}"
            months_list.append((label_text, m_start, m_end))

        for lbl, m_s, m_e in months_list:
            monthly_trend_labels.append(lbl)
            def _get_month_sum(m_name, d_state, a_field, d_field='transfer_date'):
                d = [
                    '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
                    ('state', '=', d_state),
                    '|',
                    '&', (d_field, '>=', m_s), (d_field, '<=', m_e),
                    '&', (d_field, '=', False), ('create_date', '>=', f'{m_s} 00:00:00'), ('create_date', '<=', f'{m_e} 23:59:59')
                ]
                if matching_project_ids:
                    d.append(('project_id', 'in', matching_project_ids))
                res = self.env[m_name].sudo().search(d)
                return round(sum(res.mapped(a_field)), 2)

            monthly_trend_adv.append(_get_month_sum('bank.settlement.advance', 'paid', 'amount', 'transfer_date'))
            monthly_trend_gov.append(_get_month_sum('bank.settlement.government.fee', 'done', 'total_amount', 'transfer_date'))
            monthly_trend_veh.append(_get_month_sum('bank.settlement.vehicle.transfer', 'done', 'amount', 'transfer_date'))
            monthly_trend_med.append(_get_month_sum('bank.settlement.medical.insurance', 'done', 'amount', 'transfer_date'))
            monthly_trend_rep.append(_get_month_sum('bank.settlement.representative', 'done', 'amount', 'date'))

        # د. أعلى أنواع الرسوم الحكومية تكلفة (Top Government Fee Types)
        top_gov_fees_labels = []
        top_gov_fees_data = []
        gov_fee_domain = [
            '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
            ('state', '=', 'done')
        ]
        if matching_project_ids:
            gov_fee_domain.append(('project_id', 'in', matching_project_ids))
        if current_start and current_end:
            gov_fee_domain.extend([
                '|',
                '&', ('transfer_date', '>=', current_start), ('transfer_date', '<=', current_end),
                '&', ('transfer_date', '=', False), ('create_date', '>=', f'{current_start} 00:00:00'), ('create_date', '<=', f'{current_end} 23:59:59')
            ])
        gov_grouped = self.env['bank.settlement.government.fee'].sudo()._read_group(
            gov_fee_domain, groupby=['fee_type_id'], aggregates=['total_amount:sum'], order='total_amount:sum desc', limit=6
        )
        for fee_type, amt in gov_grouped:
            ft_name = fee_type.name if fee_type else _('أخرى')
            top_gov_fees_labels.append(ft_name)
            top_gov_fees_data.append(round(amt or 0.0, 2))

        # هـ. أعلى أنواع تحويلات ومصاريف المركبات (Top Vehicle Transfer Types)
        top_veh_labels = []
        top_veh_data = []
        veh_domain = [
            '|', ('company_id', '=', False), ('company_id', 'in', company_ids),
            ('state', '=', 'done')
        ]
        if matching_project_ids:
            veh_domain.append(('project_id', 'in', matching_project_ids))
        if current_start and current_end:
            veh_domain.extend([
                '|',
                '&', ('transfer_date', '>=', current_start), ('transfer_date', '<=', current_end),
                '&', ('transfer_date', '=', False), ('create_date', '>=', f'{current_start} 00:00:00'), ('create_date', '<=', f'{current_end} 23:59:59')
            ])
        veh_grouped = self.env['bank.settlement.vehicle.transfer'].sudo()._read_group(
            veh_domain, groupby=['transfer_type_id'], aggregates=['amount:sum'], order='amount:sum desc', limit=6
        )
        for transfer_type, amt in veh_grouped:
            tt_name = transfer_type.name if transfer_type else _('أخرى')
            top_veh_labels.append(tt_name)
            top_veh_data.append(round(amt or 0.0, 2))

        # 5. سجل أحدث العمليات والمدفوعات (Recent Transactions)
        recent_items = []
        models_meta = [
            ('bank.settlement.advance', _('سلفة'), 'advance', 'amount'),
            ('bank.settlement.government.fee', _('رسوم حكومية'), 'government_fee', 'total_amount'),
            ('bank.settlement.vehicle.transfer', _('تحويل مركبة'), 'vehicle_transfer', 'amount'),
            ('bank.settlement.medical.insurance', _('تأمين طبي'), 'medical_insurance', 'amount'),
            ('bank.settlement.representative', _('تصفية مندوب'), 'representative', 'amount'),
        ]

        state_labels_map = {
            'draft': _('مسودة'),
            'waiting_approval': _('بانتظار الموافقة'),
            'pm_approved': _('وافق مسؤول المشروع'),
            'under_review': _('تحت المراجعة'),
            'approved': _('تمت الموافقة'),
            'confirmed': _('مؤكدة'),
            'paid': _('تم الصرف'),
            'done': _('مسددة / منفذة'),
            'rejected': _('مرفوضة'),
            'cancel': _('ملغاة'),
        }

        for model_name, type_title, type_code, amt_col in models_meta:
            rec_dom = ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]
            if matching_project_ids:
                rec_dom.append(('project_id', 'in', matching_project_ids))
            records = self.env[model_name].sudo().search(rec_dom, order='create_date desc', limit=4)
            for r in records:
                emp_name = r.employee_id.name if getattr(r, 'employee_id', False) else '-'
                if not emp_name or emp_name == '-':
                    if getattr(r, 'partner_id', False):
                        emp_name = r.partner_id.name
                    elif getattr(r, 'vendor_id', False):
                        emp_name = r.vendor_id.name

                proj_name = r.project_id.name if getattr(r, 'project_id', False) else '-'
                comp_name = r.company_id.name if getattr(r, 'company_id', False) else _('عامة')
                dt = r.transfer_date or (r.create_date.date() if r.create_date else today)

                recent_items.append({
                    'id': r.id,
                    'model': model_name,
                    'name': r.name or _('جديد'),
                    'type_title': type_title,
                    'type_code': type_code,
                    'employee_name': emp_name,
                    'project_name': proj_name,
                    'company_name': comp_name,
                    'amount': round(getattr(r, amt_col, 0.0) or 0.0, 2),
                    'date': str(dt),
                    'create_date': r.create_date or fields.Datetime.now(),
                    'state': r.state,
                    'state_label': state_labels_map.get(r.state, r.state),
                })

        # فرز أحدث 10 معاملات زمنياً تنازلياً
        recent_items.sort(key=lambda x: x['create_date'], reverse=True)
        recent_transactions = recent_items[:10]
        for item in recent_transactions:
            item.pop('create_date', None)

        # 6. قائمة المشاريع/المنصات لفلتر الواجهة (تجميع فريد حسب الاسم لتغطية كافة الشركات النشطة)
        all_projects = self.env['project.project'].sudo().search([
            '|', ('company_id', '=', False), ('company_id', 'in', company_ids)
        ], order='name asc')
        unique_platforms = []
        seen_names = set()
        for p in all_projects:
            p_name = (p.name or '').strip()
            if p_name and p_name not in seen_names:
                seen_names.add(p_name)
                unique_platforms.append({
                    'id': p.id,
                    'name': p_name,
                })

        return {
            'currency': currency_data,
            'kpis': {
                'total_settled_amount': round(total_settled_amt, 2),
                'total_settled_count': total_settled_count,
                'growth_rate': growth_rate,
                'advances': {
                    'amount': round(adv_amt, 2),
                    'count': adv_count,
                },
                'government_fees': {
                    'amount': round(gov_amt, 2),
                    'count': gov_count,
                },
                'vehicle_transfers': {
                    'amount': round(veh_amt, 2),
                    'count': veh_count,
                },
                'medical_insurance': {
                    'amount': round(med_amt, 2),
                    'count': med_count,
                },
                'representative_settlements': {
                    'amount': round(rep_amt, 2),
                    'count': rep_count,
                },
            },
            'approvals': {
                'adv_wait_pm': {'count': adv_wait_pm_count, 'amount': round(adv_wait_pm_amt, 2)},
                'adv_wait_gm': {'count': adv_wait_gm_count, 'amount': round(adv_wait_gm_amt, 2)},
                'adv_appr_unpaid': {'count': adv_appr_unpaid_count, 'amount': round(adv_appr_unpaid_amt, 2)},
                'gov_under_review': {'count': gov_review_count, 'amount': round(gov_review_amt, 2)},
                'veh_under_review': {'count': veh_review_count, 'amount': round(veh_review_amt, 2)},
                'med_under_review': {'count': med_review_count, 'amount': round(med_review_amt, 2)},
                'rep_under_review': {'count': rep_review_count, 'amount': round(rep_review_amt, 2)},
                'returned_correction_count': returned_count,
            },
            'alerts': {
                'due_prepaid_count': due_prepaid_count,
                'due_prepaid_amount': round(due_prepaid_amt, 2),
            },
            'charts': {
                'platform': {
                    'labels': platform_labels,
                    'data': platform_data,
                },
                'category': {
                    'labels': category_labels,
                    'data': category_data,
                },
                'monthly_trend': {
                    'labels': monthly_trend_labels,
                    'adv': monthly_trend_adv,
                    'gov': monthly_trend_gov,
                    'veh': monthly_trend_veh,
                    'med': monthly_trend_med,
                    'rep': monthly_trend_rep,
                },
                'top_gov_fees': {
                    'labels': top_gov_fees_labels,
                    'data': top_gov_fees_data,
                },
                'top_vehicle_types': {
                    'labels': top_veh_labels,
                    'data': top_veh_data,
                },
            },
            'recent_transactions': recent_transactions,
            'projects': unique_platforms,
        }

    @api.model
    def action_post_all_due_prepaid(self):
        """ترحيل كافة فترات الدفعات المقدمة المستحقة بنقرة واحدة من لوحة المؤشرات."""
        user = self.env.user
        is_reviewer = user.has_group('bank_settlement.group_bank_settlement_reviewer')
        is_manager = user.has_group('bank_settlement.group_bank_settlement_manager')
        if not (is_reviewer or is_manager):
            raise UserError(_('عذراً، ترحيل أسطر الاستحقاق متاح للمحاسب أو المدير العام فقط.'))

        today = fields.Date.context_today(self)
        due_lines = self.env['bank.settlement.prepaid.line'].sudo().search([
            '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids),
            ('state', '=', 'draft'),
            ('period_end_date', '<=', today),
        ])
        if not due_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('الدفعات المقدمة'),
                    'message': _('لا توجد فترات مستحقة للترحيل حالياً.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        due_lines._post_entry()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('تم الترحيل بنجاح'),
                'message': _('تم ترحيل %s فترة مستحقة بنجاح وإنشاء القيود المحاسبية لها.') % len(due_lines),
                'type': 'success',
                'sticky': False,
            }
        }
