/** @odoo-module **/

import { Component, useState, onWillStart, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
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
        this.branchChartRef = useRef("branchChart");
        this.costChartRef = useRef("costChart");
        this.charts = {};

        this.state = useState({
            loading: true,
            month: new Date().toISOString().slice(0, 7) + "-01",
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
            },
            () => [this.state.loading, this.state.data]
        );
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("fleet.dashboard", "get_dashboard_data", [], {
            month: this.state.month,
        });
        this.state.loading = false;
    }

    async onMonthChange(ev) {
        this.state.month = ev.target.value + "-01";
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

    money(value) {
        return (value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    renderCharts() {
        const Chart = window.Chart;
        if (!Chart) {
            return;
        }
        const palette = ["#2563eb", "#10b981", "#f59e0b", "#7c3aed", "#ef4444", "#0ea5e9"];
        const destroy = (key) => {
            if (this.charts[key]) {
                this.charts[key].destroy();
                this.charts[key] = null;
            }
        };
        const branch = this.state.data.by_branch || [];
        // الإتلاف خارج الشرط: حين تصير البيانات فارغة يختفي الـ canvas من
        // الشجرة بينما يبقى كائن Chart ومستمع تغيير الحجم معلَّقين عليه.
        destroy("branch");
        if (this.branchChartRef.el) {
            this.charts.branch = new Chart(this.branchChartRef.el, {
                type: "doughnut",
                data: {
                    labels: branch.map((r) => r.label),
                    datasets: [{
                        data: branch.map((r) => r.value),
                        backgroundColor: branch.map((l, i) => palette[i % palette.length]),
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "62%",
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { usePointStyle: true, boxWidth: 8, padding: 14 },
                        },
                    },
                },
            });
        }
        const top = this.state.data.top_cost || [];
        destroy("cost");
        if (this.costChartRef.el) {
            this.charts.cost = new Chart(this.costChartRef.el, {
                type: "bar",
                data: {
                    labels: top.map((r) => r.label),
                    datasets: [{
                        data: top.map((r) => r.value),
                        backgroundColor: "#2563eb",
                        hoverBackgroundColor: "#1d4ed8",
                        borderRadius: 8,
                        maxBarThickness: 34,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: "y",
                    plugins: { legend: { display: false } },
                    scales: {
                        x: {
                            grid: { color: "#eef2f7", drawBorder: false },
                            ticks: { color: "#94a3b8", font: { size: 11 } },
                        },
                        y: {
                            grid: { display: false, drawBorder: false },
                            ticks: { color: "#475569", font: { size: 11 } },
                        },
                    },
                },
            });
        }
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
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "fleet.vehicle",
            res_id: vehicleId,
            views: [[false, "form"]],
        });
    }

    openPlan(planId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "fleet.maintenance.plan",
            res_id: planId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("fleet_dashboard", FleetDashboard);
