/** @odoo-module **/

import { Component, useState, onWillStart, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { loadBundle } from "@web/core/assets";

export class RecruitmentWorkflowDashboard extends Component {
    static template = "recruitment_workflow.RecruitmentWorkflowDashboard";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.funnelChartRef = useRef("funnelChart");
        this.platformChartRef = useRef("platformChart");
        this.monthlyTrendChartRef = useRef("monthlyTrendChart");
        this.compensationChartRef = useRef("compensationChart");
        this.fleetChartRef = useRef("fleetChart");

        this.chartInstances = {};

        this.state = useState({
            isLoading: true,
            selectedPeriod: "this_month",
            selectedProjectId: 0,
            kpis: {
                total_requests: 0,
                growth_rate: 0,
                in_progress_count: 0,
                started_count: 0,
                rejected_count: 0,
                success_rate: 0,
                rejection_rate: 0,
                active_couriers_count: 0,
                total_vehicles: 0,
                assigned_vehicles: 0,
                available_vehicles: 0,
                fleet_allocation_rate: 0,
                platform_transfers_count: 0,
            },
            approvals: {
                wait_pm: 0,
                wait_ops: 0,
                wait_gm: 0,
                wait_paid: 0,
                sponsorship_transfer: 0,
                sponsorship_done: 0,
                wait_car: 0,
                pending_transfers: 0,
                pending_veh_changes: 0,
            },
            alerts: {
                iqama_expiring_count: 0,
                car_shortage_alert: {
                    has_shortage: false,
                    waiting_car: 0,
                    available_vehicles: 0,
                },
                incomplete_att_count: 0,
            },
            charts: {},
            recentRequests: [],
            projects: [],
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
            const data = await this.orm.call("recruitment.workflow.dashboard", "get_dashboard_data", [], {
                period: this.state.selectedPeriod,
                project_id: parseInt(this.state.selectedProjectId) || false,
            });

            this.state.kpis = data.kpis;
            this.state.approvals = data.approvals;
            this.state.alerts = data.alerts;
            this.state.charts = data.charts;
            this.state.recentRequests = data.recent_requests;
            this.state.projects = data.projects;

            // التحقق من أن المنصة المختارة ما زالت موجودة في قائمة المشاريع المتاحة
            const projId = parseInt(this.state.selectedProjectId) || 0;
            if (projId && !data.projects.some((p) => p.id === projId)) {
                this.state.selectedProjectId = 0;
            }
        } catch (error) {
            console.error("Error loading recruitment workflow dashboard data:", error);
            this.notification.add(_t("تعذر تحميل بيانات لوحة مؤشرات التوظيف، يرجى المحاولة لاحقاً."), {
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

        // 1. مسار مراحل التوظيف (Recruitment Funnel)
        if (this.funnelChartRef.el && this.state.charts.funnel) {
            const fn = this.state.charts.funnel;
            const ctx = this.funnelChartRef.el.getContext("2d");
            this.chartInstances.funnel = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: fn.labels,
                    datasets: [
                        {
                            label: _t("عدد الطلبات"),
                            data: fn.data,
                            backgroundColor: [
                                "#3B82F6", "#6366F1", "#8B5CF6", "#EC4899",
                                "#F59E0B", "#10B981", "#06B6D4", "#64748B", "#059669"
                            ],
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { beginAtZero: true, grid: { display: false } },
                        y: { grid: { display: false } },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { rtl: true },
                    },
                },
            });
        }

        // 2. التوزيع النسبي للمناديب حسب المنصة (Platform Distribution)
        if (this.platformChartRef.el && this.state.charts.platform) {
            const pf = this.state.charts.platform;
            const ctx = this.platformChartRef.el.getContext("2d");
            const colors = [
                "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
                "#06B6D4", "#EC4899", "#84CC16", "#6366F1", "#14B8A6"
            ];
            this.chartInstances.platform = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: pf.labels,
                    datasets: [
                        {
                            data: pf.data,
                            backgroundColor: colors.slice(0, pf.labels.length),
                            borderWidth: 2,
                            borderColor: "#ffffff",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "bottom", rtl: true },
                        tooltip: { rtl: true },
                    },
                    cutout: "65%",
                },
            });
        }

        // 3. الاتجاه الزمني الشهري للتوظيف (Monthly Trend)
        if (this.monthlyTrendChartRef.el && this.state.charts.monthly_trend) {
            const mt = this.state.charts.monthly_trend;
            const ctx = this.monthlyTrendChartRef.el.getContext("2d");
            this.chartInstances.monthlyTrend = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: mt.labels,
                    datasets: [
                        {
                            label: _t("طلبات جديدة"),
                            data: mt.new_requests,
                            backgroundColor: "#3B82F6",
                            borderRadius: 4,
                        },
                        {
                            label: _t("تمت المباشرة"),
                            data: mt.started,
                            backgroundColor: "#10B981",
                            borderRadius: 4,
                        },
                        {
                            label: _t("مرفوضة"),
                            data: mt.rejected,
                            backgroundColor: "#EF4444",
                            borderRadius: 4,
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
                        legend: { position: "top", rtl: true },
                        tooltip: { rtl: true },
                    },
                },
            });
        }

        // 4. توزيع أنظمة العمل (Compensation Types)
        if (this.compensationChartRef.el && this.state.charts.compensation) {
            const cp = this.state.charts.compensation;
            const ctx = this.compensationChartRef.el.getContext("2d");
            this.chartInstances.compensation = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: cp.labels,
                    datasets: [
                        {
                            data: cp.data,
                            backgroundColor: ["#F59E0B", "#10B981", "#6366F1", "#06B6D4", "#EC4899"],
                            borderWidth: 2,
                            borderColor: "#ffffff",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "bottom", rtl: true },
                        tooltip: { rtl: true },
                    },
                    cutout: "60%",
                },
            });
        }

        // 5. جاهزية أسطول المركبات (Fleet Status)
        if (this.fleetChartRef.el && this.state.charts.fleet) {
            const fl = this.state.charts.fleet;
            const ctx = this.fleetChartRef.el.getContext("2d");
            this.chartInstances.fleet = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: fl.labels,
                    datasets: [
                        {
                            data: fl.data,
                            backgroundColor: ["#8B5CF6", "#10B981"],
                            borderWidth: 2,
                            borderColor: "#ffffff",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "bottom", rtl: true },
                        tooltip: { rtl: true },
                    },
                    cutout: "60%",
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

    openBulkAssignWizard() {
        this.actionService.doAction("recruitment_workflow.action_hr_employee_platform_bulk_assign_wizard");
    }

    openExpiringIqamas() {
        const today = new Date();
        const sixtyDaysLater = new Date();
        sixtyDaysLater.setDate(today.getDate() + 60);
        const dateStr = sixtyDaysLater.toISOString().split("T")[0];

        this.openRecords(
            "hr.employee",
            [
                ["is_courier", "=", true],
                ["iqama_expiry_date", "!=", false],
                ["iqama_expiry_date", "<=", dateStr],
            ],
            _t("المناديب ذوي الإقامات المنتهية أو القريبة من الانتهاء")
        );
    }
}

registry.category("actions").add("recruitment_workflow_dashboard", RecruitmentWorkflowDashboard);
