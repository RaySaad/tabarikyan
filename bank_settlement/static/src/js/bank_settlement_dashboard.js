/** @odoo-module **/

import { Component, useState, onWillStart, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { loadBundle } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class BankSettlementDashboard extends Component {
    static template = "bank_settlement.BankSettlementDashboard";
    // أودو تمرّر لكل "إجراء عميل" خصائصها القياسية (action،
    // actionId، updateActionState، className...). تركها غير معلَنة
    // يُسقط الشاشة في أودو 19 بخطأ OwlError: Invalid props.
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.monthlyTrendChartRef = useRef("monthlyTrendChart");
        this.platformChartRef = useRef("platformChart");
        this.categoryChartRef = useRef("categoryChart");
        this.topGovFeesChartRef = useRef("topGovFeesChart");
        this.topVehicleTypesChartRef = useRef("topVehicleTypesChart");

        this.chartInstances = {};

        this.state = useState({
            isLoading: true,
            selectedPeriod: "this_month",
            selectedProjectId: 0,
            kpis: {
                total_settled_amount: 0,
                total_settled_count: 0,
                growth_rate: 0,
                advances: { amount: 0, count: 0 },
                government_fees: { amount: 0, count: 0 },
                vehicle_transfers: { amount: 0, count: 0 },
                medical_insurance: { amount: 0, count: 0 },
                representative_settlements: { amount: 0, count: 0 },
            },
            approvals: {
                adv_wait_pm: { count: 0, amount: 0 },
                adv_wait_gm: { count: 0, amount: 0 },
                adv_appr_unpaid: { count: 0, amount: 0 },
                gov_under_review: { count: 0, amount: 0 },
                veh_under_review: { count: 0, amount: 0 },
                med_under_review: { count: 0, amount: 0 },
                rep_under_review: { count: 0, amount: 0 },
                returned_correction_count: 0,
            },
            alerts: {
                due_prepaid_count: 0,
                due_prepaid_amount: 0,
            },
            charts: {},
            recentTransactions: [],
            projects: [],
            currency: { symbol: "ر.س", position: "after" },
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadDashboardData();
        });

        useEffect(
            () => {
                if (!this.state.isLoading) {
                    this.renderAllCharts();
                }
                return () => {
                    this.destroyAllCharts();
                };
            },
            () => [this.state.isLoading, this.state.selectedPeriod, this.state.selectedProjectId]
        );
    }

    async loadDashboardData() {
        this.state.isLoading = true;
        try {
            const data = await this.orm.call("bank.settlement.dashboard", "get_dashboard_data", [], {
                period: this.state.selectedPeriod,
                project_id: parseInt(this.state.selectedProjectId) || false,
            });

            this.state.kpis = data.kpis;
            this.state.approvals = data.approvals;
            this.state.alerts = data.alerts;
            this.state.charts = data.charts;
            this.state.recentTransactions = data.recent_transactions;
            this.state.projects = data.projects;
            this.state.currency = data.currency;

            // التحقق من أن المنصة المختارة ما زالت موجودة في قائمة المشاريع المتاحة
            const projId = parseInt(this.state.selectedProjectId) || 0;
            if (projId && !data.projects.some((p) => p.id === projId)) {
                this.state.selectedProjectId = 0;
            }
        } catch (error) {
            console.error("Error loading bank settlement dashboard data:", error);
            this.notification.add(_t("تعذر تحميل بيانات لوحة المؤشرات، يرجى المحاولة لاحقاً."), {
                type: "danger",
            });
        } finally {
            this.state.isLoading = false;
        }
    }

    async onPeriodChange(ev) {
        this.state.selectedPeriod = ev.target.value;
        await this.loadDashboardData();
    }

    async onProjectChange(ev) {
        this.state.selectedProjectId = ev.target.value;
        await this.loadDashboardData();
    }

    async refreshDashboard() {
        await this.loadDashboardData();
        this.notification.add(_t("تم تحديث بيانات لوحة المؤشرات بنجاح."), {
            type: "success",
        });
    }

    formatCurrency(value) {
        if (value === undefined || value === null) {
            value = 0;
        }
        const formattedNumber = Number(value).toLocaleString("ar-SA", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        if (this.state.currency.position === "before") {
            return `${this.state.currency.symbol} ${formattedNumber}`;
        }
        return `${formattedNumber} ${this.state.currency.symbol}`;
    }

    destroyAllCharts() {
        Object.keys(this.chartInstances).forEach((key) => {
            if (this.chartInstances[key]) {
                this.chartInstances[key].destroy();
                this.chartInstances[key] = null;
            }
        });
    }

    renderAllCharts() {
        this.destroyAllCharts();

        // 1. الاتجاه الشهري للمصروفات (Monthly Trend)
        if (this.monthlyTrendChartRef.el && this.state.charts.monthly_trend) {
            const mt = this.state.charts.monthly_trend;
            const ctx = this.monthlyTrendChartRef.el.getContext("2d");
            this.chartInstances.monthlyTrend = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: mt.labels,
                    datasets: [
                        { label: _t("السلف"), data: mt.adv, backgroundColor: "#6366F1", borderRadius: 4 },
                        { label: _t("الرسوم الحكومية"), data: mt.gov, backgroundColor: "#0EA5E9", borderRadius: 4 },
                        { label: _t("تحويلات المركبات"), data: mt.veh, backgroundColor: "#F59E0B", borderRadius: 4 },
                        { label: _t("التأمين الطبي"), data: mt.med, backgroundColor: "#10B981", borderRadius: 4 },
                        { label: _t("تصفيات المناديب"), data: mt.rep, backgroundColor: "#EF4444", borderRadius: 4 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { stacked: true, grid: { display: false } },
                        y: { stacked: true, beginAtZero: true },
                    },
                    plugins: {
                        legend: { position: "top", rtl: true },
                        tooltip: { rtl: true },
                    },
                },
            });
        }

        // 2. التكاليف حسب المنصة (Platform Breakdown)
        if (this.platformChartRef.el && this.state.charts.platform) {
            const plt = this.state.charts.platform;
            const ctx = this.platformChartRef.el.getContext("2d");
            const hasData = plt.data && plt.data.length > 0 && plt.data.some((d) => d > 0);
            this.chartInstances.platform = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: hasData ? plt.labels : [_t("لا توجد بيانات")],
                    datasets: [
                        {
                            data: hasData ? plt.data : [1],
                            backgroundColor: hasData
                                ? ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#14B8A6", "#64748B", "#F97316", "#06B6D4", "#84CC16"]
                                : ["#E2E8F0"],
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "68%",
                    plugins: {
                        legend: { position: "bottom", rtl: true },
                        tooltip: {
                            rtl: true,
                            enabled: hasData,
                            callbacks: {
                                label: (context) => {
                                    const value = context.raw || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    const formattedVal = this.formatCurrency(value);
                                    return ` ${context.label}: ${formattedVal} (${percentage}%)`;
                                },
                            },
                        },
                    },
                },
            });
        }

        // 3. التوزيع حسب نوع المصروف (Category Breakdown)
        if (this.categoryChartRef.el && this.state.charts.category) {
            const cat = this.state.charts.category;
            const ctx = this.categoryChartRef.el.getContext("2d");
            const hasData = cat.data && cat.data.some((d) => d > 0);
            this.chartInstances.category = new Chart(ctx, {
                type: "pie",
                data: {
                    labels: hasData ? cat.labels : [_t("لا توجد بيانات")],
                    datasets: [
                        {
                            data: hasData ? cat.data : [1],
                            backgroundColor: hasData
                                ? ["#6366F1", "#0EA5E9", "#F59E0B", "#10B981", "#EF4444"]
                                : ["#E2E8F0"],
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "bottom", rtl: true },
                        tooltip: { rtl: true, enabled: hasData },
                    },
                },
            });
        }

        // 4. أعلى الرسوم الحكومية (Top Gov Fees)
        if (this.topGovFeesChartRef.el && this.state.charts.top_gov_fees) {
            const tg = this.state.charts.top_gov_fees;
            const ctx = this.topGovFeesChartRef.el.getContext("2d");
            this.chartInstances.topGovFees = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: tg.labels,
                    datasets: [
                        {
                            label: _t("المبلغ الإجمالي"),
                            data: tg.data,
                            backgroundColor: "#0EA5E9",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { beginAtZero: true },
                        y: { grid: { display: false } },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { rtl: true },
                    },
                },
            });
        }

        // 5. أعلى مصاريف المركبات (Top Vehicle Transfer Types)
        if (this.topVehicleTypesChartRef.el && this.state.charts.top_vehicle_types) {
            const tv = this.state.charts.top_vehicle_types;
            const ctx = this.topVehicleTypesChartRef.el.getContext("2d");
            this.chartInstances.topVeh = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: tv.labels,
                    datasets: [
                        {
                            label: _t("المبلغ الإجمالي"),
                            data: tv.data,
                            backgroundColor: "#F59E0B",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { grid: { display: false } },
                        y: { beginAtZero: true },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { rtl: true },
                    },
                },
            });
        }
    }

    // --- إجراءات التنقل وفتح السجلات (Drilldown Helpers) ---

    openRecords(resModel, domain = [], title = "") {
        this.actionService.doAction({
            name: title || _t("السجلات"),
            type: "ir.actions.act_window",
            res_model: resModel,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: domain,
            target: "current",
        });
    }

    createRecord(resModel, title = "") {
        this.actionService.doAction({
            name: title || _t("سجل جديد"),
            type: "ir.actions.act_window",
            res_model: resModel,
            views: [[false, "form"]],
            target: "current",
        });
    }

    viewRecord(resModel, resId, title = "") {
        this.actionService.doAction({
            name: title || _t("تفاصيل السجل"),
            type: "ir.actions.act_window",
            res_model: resModel,
            views: [[false, "form"]],
            res_id: resId,
            target: "current",
        });
    }

    openEmployeeStatementWizard() {
        this.actionService.doAction("bank_settlement.action_bank_settlement_employee_statement_wizard");
    }

    async postDuePrepaid() {
        try {
            const action = await this.orm.call("bank.settlement.dashboard", "action_post_all_due_prepaid", []);
            if (action && action.type === "ir.actions.client") {
                this.actionService.doAction(action);
            }
            await this.loadDashboardData();
        } catch (error) {
            console.error("Error posting due prepaid lines:", error);
            this.notification.add(_t("حدث خطأ أثناء ترحيل أسطر الاستحقاق."), {
                type: "danger",
            });
        }
    }
}

registry.category("actions").add("bank_settlement_dashboard", BankSettlementDashboard);

