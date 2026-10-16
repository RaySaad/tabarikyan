/** @odoo-module **/

import { Component, useState, onWillStart, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { loadBundle } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class FleetDashboard extends Component {
    static template = "fleet_maintenance.FleetDashboard";
    // خصائص الإجراء العميل القياسية - تركها غير معلَنة يُسقط الشاشة في
    // أودو 19 بخطأ OwlError: Invalid props (عطل وقع فعلاً في لوحتين
    // سابقتين عندنا).
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.trendChartRef = useRef("trendChart");
        this.branchChartRef = useRef("branchChart");
        this.costChartRef = useRef("costChart");
        this.charts = {};

        this.state = useState({
            loading: true,
            month: new Date().toISOString().slice(0, 7) + "-01",
            branchId: 0,
            data: null,
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });

        useEffect(
            () => {
                if (!this.state.loading && this.state.data) {
                    this.renderCharts();
                }
                return () => this.destroyCharts();
            },
            () => [this.state.loading, this.state.data]
        );
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("fleet.dashboard", "get_dashboard_data", [], {
            month: this.state.month,
            branch_id: this.state.branchId || null,
        });
        this.state.loading = false;
    }

    async refresh() {
        await this.load();
        this.notification.add(_t("حُدِّثت بيانات اللوحة."), { type: "success" });
    }

    async onMonthChange(ev) {
        this.state.month = ev.target.value + "-01";
        await this.load();
    }

    async onBranchChange(ev) {
        this.state.branchId = parseInt(ev.target.value, 10) || 0;
        await this.load();
    }

    /** محيط الحلقة = 2πr (r=50) - نرسم منه نسبة التشغيل. */
    get ringDash() {
        const circumference = 2 * Math.PI * 50;
        const pct = Math.max(0, Math.min(100, this.kpi.utilisation || 0));
        return `${(circumference * pct) / 100} ${circumference}`;
    }

    get kpi() {
        return (this.state.data && this.state.data.kpi) || {};
    }

    /** الرسم الزمني لا يُعرض وكل أشهره أصفار - يُستبدل بحالة فراغ. */
    get hasTrend() {
        const trend = this.state.data && this.state.data.trend;
        if (!trend) {
            return false;
        }
        return ["rent", "service", "fuel", "accident"].some((key) =>
            (trend[key] || []).some((value) => value > 0)
        );
    }

    /** ارتفاع يتبع عدد الأعمدة: خمس مركبات تملأ اللوح، ومركبتان لا
     *  تتركان فراغاً كبيراً تحتهما. */
    get costChartHeight() {
        const rows = ((this.state.data && this.state.data.top_cost) || []).length;
        return Math.max(150, rows * 46 + 50) + "px";
    }

    money(value) {
        const amount = (value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        const currency = (this.state.data && this.state.data.currency) || {};
        return currency.symbol ? `${amount} ${currency.symbol}` : amount;
    }

    typeTone(type) {
        return {
            contract: "blue",
            accident: "red",
            charge: "green",
            fuel: "violet",
        }[type] || "grey";
    }

    stateTone(state) {
        return {
            active: "green",
            posted: "green",
            done: "green",
            confirmed: "blue",
            draft: "grey",
            ended: "grey",
            closed: "grey",
            cancel: "red",
        }[state] || "grey";
    }

    // ------------------------------------------------------------------
    // الرسوم
    // ------------------------------------------------------------------
    destroyCharts() {
        Object.keys(this.charts).forEach((key) => {
            if (this.charts[key]) {
                this.charts[key].destroy();
                this.charts[key] = null;
            }
        });
    }

    /** ألوان النص والشبكة تُقرأ من سمة أودو الجارية فتصلح للوضعين. */
    get chartTheme() {
        const styles = getComputedStyle(document.body);
        return {
            ink: styles.getPropertyValue("--body-color").trim() || "#475569",
            muted: styles.getPropertyValue("--secondary-color").trim() || "#94a3b8",
            grid: styles.getPropertyValue("--border-color").trim() || "#eef2f7",
            surface: styles.getPropertyValue("--body-bg").trim() || "#ffffff",
        };
    }

    renderCharts() {
        const Chart = window.Chart;
        if (!Chart) {
            return;
        }
        // الإتلاف خارج شروط وجود المراجع: حين تصير البيانات فارغة يختفي
        // الـ canvas من الشجرة بينما يبقى كائن Chart معلَّقاً عليه.
        this.destroyCharts();

        const theme = this.chartTheme;
        const palette = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#06b6d4"];
        const legend = {
            display: true,
            position: "bottom",
            labels: {
                color: theme.ink,
                usePointStyle: true,
                pointStyle: "circle",
                boxWidth: 8,
                padding: 14,
                font: { size: 11 },
            },
        };

        // -- تطور ستة أشهر: أعمدة مكدَّسة للتكاليف وخط للأجرة -----------
        const trend = this.state.data.trend || {};
        if (this.trendChartRef.el) {
            this.charts.trend = new Chart(this.trendChartRef.el, {
                data: {
                    labels: trend.labels || [],
                    datasets: [{
                        type: "line",
                        label: _t("أجرة مرحَّلة"),
                        data: trend.rent || [],
                        borderColor: "#10b981",
                        backgroundColor: "rgba(16, 185, 129, 0.14)",
                        borderWidth: 3,
                        tension: 0.35,
                        fill: true,
                        pointRadius: 4,
                        pointBackgroundColor: "#10b981",
                        order: 0,
                    }, {
                        type: "bar",
                        label: _t("ورشة"),
                        data: trend.service || [],
                        backgroundColor: "#3b82f6",
                        borderRadius: 6,
                        maxBarThickness: 26,
                        stack: "cost",
                        order: 1,
                    }, {
                        type: "bar",
                        label: _t("وقود (الفروع)"),
                        data: trend.fuel || [],
                        backgroundColor: "#8b5cf6",
                        borderRadius: 6,
                        maxBarThickness: 26,
                        stack: "cost",
                        order: 1,
                    }, {
                        type: "bar",
                        label: _t("حوادث"),
                        data: trend.accident || [],
                        backgroundColor: "#ef4444",
                        borderRadius: 6,
                        maxBarThickness: 26,
                        stack: "cost",
                        order: 1,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: {
                        legend,
                        tooltip: {
                            callbacks: {
                                label: (ctx) =>
                                    `${ctx.dataset.label}: ${this.money(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        x: {
                            stacked: true,
                            grid: { display: false },
                            ticks: { color: theme.muted, font: { size: 11 } },
                        },
                        y: {
                            stacked: true,
                            grid: { color: theme.grid },
                            border: { display: false },
                            ticks: { color: theme.muted, font: { size: 11 } },
                        },
                    },
                },
            });
        }

        // -- توزيع المركبات على الفروع ------------------------------------
        const branch = this.state.data.by_branch || [];
        if (this.branchChartRef.el) {
            this.charts.branch = new Chart(this.branchChartRef.el, {
                type: "doughnut",
                data: {
                    labels: branch.map((r) => r.label),
                    datasets: [{
                        data: branch.map((r) => r.value),
                        backgroundColor: branch.map((l, i) => palette[i % palette.length]),
                        borderWidth: 2,
                        borderColor: theme.surface,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "62%",
                    plugins: { legend },
                },
            });
        }

        // -- أعلى المركبات تكلفة -------------------------------------------
        const top = this.state.data.top_cost || [];
        if (this.costChartRef.el) {
            this.charts.cost = new Chart(this.costChartRef.el, {
                type: "bar",
                data: {
                    labels: top.map((r) => r.label),
                    datasets: [{
                        data: top.map((r) => r.value),
                        backgroundColor: "#3b82f6",
                        hoverBackgroundColor: "#1d4ed8",
                        borderRadius: 8,
                        maxBarThickness: 34,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: "y",
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: { label: (ctx) => this.money(ctx.parsed.x) },
                        },
                    },
                    scales: {
                        x: {
                            grid: { color: theme.grid },
                            border: { display: false },
                            ticks: { color: theme.muted, font: { size: 11 } },
                        },
                        y: {
                            grid: { display: false },
                            border: { display: false },
                            ticks: { color: theme.ink, font: { size: 11 } },
                        },
                    },
                },
            });
        }
    }

    // ------------------------------------------------------------------
    // الإجراءات
    // ------------------------------------------------------------------
    /** التنبيهات تحمل اسم الإجراء نصاً - ننفّذ المسمى فقط لا أي دالة. */
    runAction(name) {
        const allowed = ["openDue", "openIdle", "openCharges", "openAccidents"];
        if (allowed.includes(name)) {
            this[name]();
        }
    }

    openStage(key) {
        ({
            car_requests: () => this.action.doAction(
                "recruitment_workflow.action_recruitment_request_fleet"),
            contracts: () => this.openRecords(
                "fleet.rental.contract", [["state", "=", "active"]], _t("عقود سارية")),
            accidents: () => this.openRecords(
                "fleet.accident.report", [["state", "!=", "closed"]],
                _t("بلاغات حوادث مفتوحة")),
            unpriced: () => this.openRecords(
                "fleet.accident.report",
                [["state", "!=", "closed"], ["actual_cost", "=", 0]],
                _t("بلاغات بلا تكلفة فعلية")),
            charges: () => this.openRecords(
                "fleet.branch.rental.charge", [["state", "in", ["draft", "confirmed"]]],
                _t("تحميلات غير مرحَّلة")),
        }[key] || (() => {}))();
    }

    openRecords(resModel, domain = [], name = "") {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || _t("السجلات"),
            res_model: resModel,
            domain,
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    createRecord(resModel, name = "") {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || _t("سجل جديد"),
            res_model: resModel,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openRecord(resModel, resId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openIdle() {
        this.action.doAction("fleet_branch_rental.action_fleet_vehicle_idle");
    }

    openDue() {
        this.action.doAction("fleet_maintenance.action_fleet_maintenance_plan_due");
    }

    openCharges() {
        this.action.doAction("fleet_branch_rental.action_fleet_branch_rental_charge");
    }

    openAccidents() {
        this.openRecords(
            "fleet.accident.report", [["state", "!=", "closed"]],
            _t("بلاغات حوادث مفتوحة"));
    }

    openFuel() {
        this.action.doAction("fleet_maintenance.action_fleet_fuel_log");
    }

    openEmployeeCost() {
        this.action.doAction("fleet_maintenance.action_fleet_employee_cost_report");
    }

    openCostReport() {
        this.action.doAction("fleet_maintenance.action_fleet_vehicle_cost_report");
    }

    openVehicle(vehicleId) {
        this.openRecord("fleet.vehicle", vehicleId);
    }

    openPlan(planId) {
        this.openRecord("fleet.maintenance.plan", planId);
    }
}

registry.category("actions").add("fleet_dashboard", FleetDashboard);
