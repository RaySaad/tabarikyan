# -*- coding: utf-8 -*-
import calendar
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecruitmentWorkflowDashboard(models.AbstractModel):
    """نموذج تجميع البيانات والإحصائيات للوحة مؤشرات سير عمل التوظيف (Recruitment Workflow Dashboard)."""
    _name = 'recruitment.workflow.dashboard'
    _description = 'لوحة مؤشرات سير عمل التوظيف'

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
            # بداية الأسبوع: السبت
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
        تجميع كافة بيانات لوحة مؤشرات سير عمل التوظيف:
        - بطاقات الأداء التشغيلي (KPIs)
        - مسار الموافقات والمراحل المعلقة (Approvals Pipeline)
        - التنبيهات الذكية (إقامات، سيارات، مرفقات)
        - الرسوم البيانية التفاعلية (Chart.js)
        - سجل أحدث طلبات التوظيف
        - قائمة المنصات الفريدة لفلترة الواجهة
        """
        company_ids = self.env.companies.ids
        current_start, current_end, prev_start, prev_end = self._get_period_date_range(period)
        today = fields.Date.context_today(self)

        # تحويل project_id ومطابقة كافة المنصات الحاملة لنفس الاسم عبر الشركات المحددة
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

        # نطاق الشركة الأساسي
        base_comp_domain = ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]

        # دالة مساعدة لبناء نطاق زمني
        def _apply_date_filter(domain, start_dt, end_dt, date_col='create_date'):
            d = list(domain)
            if start_dt and end_dt:
                d.extend([
                    (date_col, '>=', f'{start_dt} 00:00:00'),
                    (date_col, '<=', f'{end_dt} 23:59:59')
                ])
            return d

        # -------------------------------------------------------------
        # 1. بطاقات الأداء الرئيسية (Top KPIs)
        # -------------------------------------------------------------
        req_base_dom = list(base_comp_domain)
        if matching_project_ids:
            req_base_dom.append(('project_id', 'in', matching_project_ids))

        # طلبات الفترة الحالية
        curr_req_dom = _apply_date_filter(req_base_dom, current_start, current_end)
        total_requests = self.env['recruitment.request'].sudo().search_count(curr_req_dom)

        # طلبات الفترة السابقة للمقارنة
        prev_total_requests = 0
        if prev_start and prev_end:
            prev_req_dom = _apply_date_filter(req_base_dom, prev_start, prev_end)
            prev_total_requests = self.env['recruitment.request'].sudo().search_count(prev_req_dom)

        growth_rate = 0.0
        if prev_total_requests > 0:
            growth_rate = round(((total_requests - prev_total_requests) / prev_total_requests) * 100, 1)
        elif total_requests > 0 and prev_total_requests == 0:
            growth_rate = 100.0

        # الطلبات قيد التنفيذ والمكتملة والمرفوضة
        in_progress_count = self.env['recruitment.request'].sudo().search_count(
            curr_req_dom + [('state', '=', 'in_progress')]
        )
        started_count = self.env['recruitment.request'].sudo().search_count(
            curr_req_dom + [('state', '=', 'done')]
        )
        rejected_count = self.env['recruitment.request'].sudo().search_count(
            curr_req_dom + [('state', '=', 'rejected')]
        )

        success_rate = round((started_count / total_requests * 100), 1) if total_requests > 0 else 0.0
        rejection_rate = round((rejected_count / total_requests * 100), 1) if total_requests > 0 else 0.0

        # إجمالي المناديب والموظفين النشطين في النظام
        emp_dom = list(base_comp_domain)
        emp_dom.append(('active', '=', True))
        if matching_project_ids:
            emp_dom.append(('project_id', 'in', matching_project_ids))
        active_couriers_count = self.env['hr.employee'].sudo().search_count(emp_dom)

        # إحصائيات الأسطول والمركبات
        veh_dom = list(base_comp_domain)
        total_vehicles = self.env['fleet.vehicle'].sudo().search_count(veh_dom)
        available_vehicles = self.env['fleet.vehicle'].sudo().search_count(
            veh_dom + [('recruitment_state', '=', 'available')]
        )
        assigned_vehicles = total_vehicles - available_vehicles
        fleet_allocation_rate = round((assigned_vehicles / total_vehicles * 100), 1) if total_vehicles > 0 else 0.0

        # طلبات نقل المنصة المكتملة في الفترة
        trans_dom = list(base_comp_domain)
        if matching_project_ids:
            trans_dom.extend(['|', ('current_project_id', 'in', matching_project_ids), ('new_project_id', 'in', matching_project_ids)])
        curr_trans_dom = _apply_date_filter(trans_dom, current_start, current_end)
        platform_transfers_count = self.env['hr.employee.platform.transfer.request'].sudo().search_count(
            curr_trans_dom + [('state', '=', 'done')]
        ) if 'hr.employee.platform.transfer.request' in self.env else 0

        # -------------------------------------------------------------
        # 2. مسار الموافقات والمراحل المعلقة (Approvals Pipeline)
        # -------------------------------------------------------------
        def _get_stage_pending(stage_code):
            dom = list(req_base_dom)
            dom.extend([('state', '=', 'in_progress'), ('stage_code', '=', stage_code)])
            return self.env['recruitment.request'].sudo().search_count(dom)

        wait_pm_count = _get_stage_pending('project_review')
        wait_ops_count = _get_stage_pending('operations_review')
        wait_gm_count = _get_stage_pending('gm_approval')
        wait_paid_count = _get_stage_pending('paid')
        sponsorship_transfer_count = _get_stage_pending('sponsorship_transfer')
        sponsorship_done_count = _get_stage_pending('sponsorship_done')
        wait_car_count = _get_stage_pending('car_request')

        # طلبات نقل منصة وتغيير مركبات معلقة تتطلب اعتماداً
        pending_transfers_count = self.env['hr.employee.platform.transfer.request'].sudo().search_count(
            list(base_comp_domain) + [('state', 'in', ('draft', 'submitted'))]
        ) if 'hr.employee.platform.transfer.request' in self.env else 0

        pending_veh_changes_count = self.env['fleet.vehicle.change.request'].sudo().search_count(
            list(base_comp_domain) + [('state', 'not in', ('done', 'rejected', 'cancel'))]
        ) if 'fleet.vehicle.change.request' in self.env else 0

        # -------------------------------------------------------------
        # 3. التنبيهات الذكية (Smart Alerts)
        # -------------------------------------------------------------
        # أ. إقامات تنتهي قريباً خلال 60 يوماً
        sixty_days_later = today + timedelta(days=60)
        iqama_alert_dom = list(base_comp_domain) + [
            ('active', '=', True),
            ('iqama_expiry_date', '!=', False),
            ('iqama_expiry_date', '<=', sixty_days_later),
        ]
        if matching_project_ids:
            iqama_alert_dom.append(('project_id', 'in', matching_project_ids))
        iqama_expiring_count = self.env['hr.employee'].sudo().search_count(iqama_alert_dom)

        # ب. طلبات متوقفة في مرحلة طلب سيارة ولا توجد سيارات كافية
        has_car_shortage = wait_car_count > available_vehicles and wait_car_count > 0
        car_shortage_alert = {
            'has_shortage': has_car_shortage,
            'waiting_car': wait_car_count,
            'available_vehicles': available_vehicles,
        }

        # ج. طلبات جديدة غير مكتملة المرفقات
        incomplete_att_dom = list(req_base_dom) + [
            ('state', '=', 'in_progress'),
            ('stage_code', '=', 'new'),
            ('attachments_complete', '=', False),
        ]
        incomplete_att_count = self.env['recruitment.request'].sudo().search_count(incomplete_att_dom)

        # -------------------------------------------------------------
        # 4. الرسوم البيانية التفاعلية (Chart.js Data)
        # -------------------------------------------------------------

        # أ. قمع تدفق مراحل التوظيف (Recruitment Funnel)
        stages = self.env['recruitment.stage'].sudo().search([], order='sequence asc')
        funnel_labels = []
        funnel_data = []
        for stg in stages:
            stg_dom = list(req_base_dom) + [('stage_id', '=', stg.id), ('state', '=', 'in_progress')]
            cnt = self.env['recruitment.request'].sudo().search_count(stg_dom)
            funnel_labels.append(stg.name)
            funnel_data.append(cnt)

        # ب. التوزيع حسب المنصة (Platform Breakdown Doughnut)
        # تعرض كافة المنصات عبر الشركات النشطة دائماً دون حجب أي منصة
        platform_dict = {}
        platform_req_dom = list(base_comp_domain)
        if current_start and current_end:
            platform_req_dom.extend([
                ('create_date', '>=', f'{current_start} 00:00:00'),
                ('create_date', '<=', f'{current_end} 23:59:59'),
            ])
        grouped_platforms = self.env['recruitment.request'].sudo()._read_group(
            platform_req_dom, groupby=['project_id'], aggregates=['__count']
        )
        for proj_rec, cnt in grouped_platforms:
            p_name = (proj_rec.name or '').strip() if proj_rec else _('بدون منصة محددة')
            platform_dict[p_name] = platform_dict.get(p_name, 0) + (cnt or 0)

        platform_labels = list(platform_dict.keys())
        platform_data = list(platform_dict.values())

        # ج. الاتجاه الشهري للتوظيف (Monthly Trend - Last 6 Months)
        monthly_labels = []
        monthly_new = []
        monthly_started = []
        monthly_rejected = []

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
            monthly_labels.append(lbl)
            m_dom = list(req_base_dom)
            m_dom.extend([
                ('create_date', '>=', f'{m_s} 00:00:00'),
                ('create_date', '<=', f'{m_e} 23:59:59'),
            ])
            n_cnt = self.env['recruitment.request'].sudo().search_count(m_dom)
            s_cnt = self.env['recruitment.request'].sudo().search_count(m_dom + [('state', '=', 'done')])
            r_cnt = self.env['recruitment.request'].sudo().search_count(m_dom + [('state', '=', 'rejected')])
            monthly_new.append(n_cnt)
            monthly_started.append(s_cnt)
            monthly_rejected.append(r_cnt)

        # د. توزيع أنظمة العمل (Compensation Types Breakdown)
        compensation_labels = []
        compensation_data = []
        grouped_comp = self.env['recruitment.request'].sudo()._read_group(
            curr_req_dom, groupby=['compensation_type_id'], aggregates=['__count']
        )
        for comp_rec, cnt in grouped_comp:
            c_name = comp_rec.name if comp_rec else _('غير محدد')
            compensation_labels.append(c_name)
            compensation_data.append(cnt)

        # هـ. حالة أسطول المركبات (Fleet Status Breakdown)
        fleet_labels = [_('مركبات مسندة للمناديب'), _('مركبات متاحة للاستلام')]
        fleet_data = [assigned_vehicles, available_vehicles]

        # -------------------------------------------------------------
        # 5. سجل أحدث طلبات التوظيف والعمليات (Recent Activity)
        # -------------------------------------------------------------
        recent_requests_dom = list(base_comp_domain)
        if matching_project_ids:
            recent_requests_dom.append(('project_id', 'in', matching_project_ids))

        recent_records = self.env['recruitment.request'].sudo().search(
            recent_requests_dom, order='create_date desc', limit=10
        )
        recent_requests = []
        for r in recent_records:
            recent_requests.append({
                'id': r.id,
                'name': r.name or _('جديد'),
                'employee_name': r.employee_name or '-',
                'identification_id': r.identification_id or '-',
                'mobile': r.mobile or '-',
                'company_name': r.company_id.name if r.company_id else _('عامة'),
                'project_name': r.project_id.name if r.project_id else '-',
                'compensation_type': r.compensation_type_id.name if r.compensation_type_id else '-',
                'stage_name': r.stage_id.name if r.stage_id else '-',
                'stage_code': r.stage_code or '',
                'state': r.state,
                'state_label': dict(r._fields['state'].selection).get(r.state, r.state),
                'date': fields.Date.to_string(r.create_date.date()) if r.create_date else str(today),
            })

        # -------------------------------------------------------------
        # 6. قائمة المنصات الفريدة لفلتر الواجهة
        # -------------------------------------------------------------
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
            'kpis': {
                'total_requests': total_requests,
                'growth_rate': growth_rate,
                'in_progress_count': in_progress_count,
                'started_count': started_count,
                'rejected_count': rejected_count,
                'success_rate': success_rate,
                'rejection_rate': rejection_rate,
                'active_couriers_count': active_couriers_count,
                'total_vehicles': total_vehicles,
                'assigned_vehicles': assigned_vehicles,
                'available_vehicles': available_vehicles,
                'fleet_allocation_rate': fleet_allocation_rate,
                'platform_transfers_count': platform_transfers_count,
            },
            'approvals': {
                'wait_pm': wait_pm_count,
                'wait_ops': wait_ops_count,
                'wait_gm': wait_gm_count,
                'wait_paid': wait_paid_count,
                'sponsorship_transfer': sponsorship_transfer_count,
                'sponsorship_done': sponsorship_done_count,
                'wait_car': wait_car_count,
                'pending_transfers': pending_transfers_count,
                'pending_veh_changes': pending_veh_changes_count,
            },
            'alerts': {
                'iqama_expiring_count': iqama_expiring_count,
                'car_shortage_alert': car_shortage_alert,
                'incomplete_att_count': incomplete_att_count,
            },
            'charts': {
                'funnel': {
                    'labels': funnel_labels,
                    'data': funnel_data,
                },
                'platform': {
                    'labels': platform_labels,
                    'data': platform_data,
                },
                'monthly_trend': {
                    'labels': monthly_labels,
                    'new_requests': monthly_new,
                    'started': monthly_started,
                    'rejected': monthly_rejected,
                },
                'compensation': {
                    'labels': compensation_labels,
                    'data': compensation_data,
                },
                'fleet': {
                    'labels': fleet_labels,
                    'data': fleet_data,
                },
            },
            'recent_requests': recent_requests,
            'projects': unique_platforms,
        }
