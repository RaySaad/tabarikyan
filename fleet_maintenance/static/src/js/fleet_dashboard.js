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
        const palette = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728", "#9467bd", "#8c564b"];
        const build = (ref, type, labels, values, label) => {
            if (!ref.el) {
                return;
            }
            if (this.charts[label]) {
                this.charts[label].destroy();
            }
            this.charts[label] = new Chart(ref.el, {
                type: type,
                data: {
                    labels: labels,
                    datasets: [{
                        label: label,
                        data: values,
                        backgroundColor: labels.map((l, i) => palette[i % palette.length]),
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: type === "doughnut" } },
                },
            });
        };
        const branch = this.state.data.by_branch || [];
        build(this.branchChartRef, "doughnut", branch.map((r) => r.label),
            branch.map((r) => r.value), "المركبات لدى الفروع");
        const top = this.state.data.top_cost || [];
        build(this.costChartRef, "bar", top.map((r) => r.label),
            top.map((r) => r.value), "أعلى المركبات تكلفة");
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
