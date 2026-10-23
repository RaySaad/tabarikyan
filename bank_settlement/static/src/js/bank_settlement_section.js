/** @odoo-module **/

import { Component, useState, onWillStart, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * لوحة قسم واحد (السلف، الرسوم الحكومية...). مكوّن واحد يخدم الأقسام
 * كلها: القسم يأتي من سياق الإجراء، والأرقام من الخادم محسوبةً
 * بصلاحية المستخدم - فما يراه في اللوحة هو ما يفتحه في القائمة.
 */
export class BankSettlementSection extends Component {
    static template = "bank_settlement.SectionDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.stateChartRef = useRef("stateChart");
        this.trendChartRef = useRef("trendChart");
        this.charts = {};

        const context = (this.props.action && this.props.action.context) || {};
        this.state = useState({
            loading: true,
            section: context.section || "advance",
            period: "this_month",
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
        this.state.data = await this.orm.call(
            "bank.settlement.dashboard", "get_section_data",
            [this.state.section, this.state.period]);
        this.state.loading = false;
    }

    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        await this.load();
    }

    money(value) {
        const amount = (value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
        const currency = (this.state.data && this.state.data.currency) || {};
        return currency.symbol ? `${amount} ${currency.symbol}` : amount;
    }

    get kpi() {
        return (this.state.data && this.state.data.kpi) || {};
    }

    get hasTrend() {
        const trend = this.state.data && this.state.data.trend;
        return !!(trend && (trend.values || []).some((value) => value > 0));
    }

    stateTone(state) {
        return {
            draft: "grey", waiting_approval: "amber", pm_approved: "violet",
            under_review: "cyan", approved: "green", confirmed: "blue",
            paid: "green", done: "green", rejected: "red", cancel: "red",
        }[state] || "grey";
    }

    // ------------------------------------------------------------------
    get chartTheme() {
        const styles = getComputedStyle(document.body);
        return {
            ink: styles.getPropertyValue("--body-color").trim() || "#334155",
            muted: styles.getPropertyValue("--secondary-color").trim() || "#94a3b8",
            grid: styles.getPropertyValue("--border-color").trim() || "#e8edf3",
            surface: styles.getPropertyValue("--body-bg").trim() || "#ffffff",
        };
    }

    destroyCharts() {
        Object.keys(this.charts).forEach((key) => {
            if (this.charts[key]) {
                this.charts[key].destroy();
                this.charts[key] = null;
            }
        });
    }

    renderCharts() {
        const Chart = window.Chart;
        if (!Chart) {
            return;
        }
        this.destroyCharts();
        const theme = this.chartTheme;
        const palette = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#06b6d4"];
        const legend = {
            position: "bottom",
            labels: {
                color: theme.ink, usePointStyle: true, pointStyle: "circle",
                boxWidth: 8, padding: 14, font: { size: 11 },
            },
        };

        const byState = this.state.data.by_state || [];
        if (this.stateChartRef.el) {
            this.charts.state = new Chart(this.stateChartRef.el, {
                type: "doughnut",
                data: {
                    labels: byState.map((row) => row.label),
                    datasets: [{
                        data: byState.map((row) => row.count),
                        backgroundColor: byState.map((row, i) => palette[i % palette.length]),
                        borderWidth: 2,
                        borderColor: theme.surface,
                        hoverOffset: 10,
                    }],
                },
                options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend } },
            });
        }

        const trend = this.state.data.trend || {};
        if (this.trendChartRef.el) {
            this.charts.trend = new Chart(this.trendChartRef.el, {
                type: "bar",
                data: {
                    labels: trend.labels || [],
                    datasets: [{
                        label: this.state.data.name,
                        data: trend.values || [],
                        backgroundColor: "#3b82f6",
                        borderRadius: 6,
                        maxBarThickness: 34,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (ctx) => this.money(ctx.parsed.y) } },
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: theme.muted, font: { size: 11 } } },
                        y: {
                            grid: { color: theme.grid }, border: { display: false },
                            ticks: { color: theme.muted, font: { size: 11 } },
                        },
                    },
                },
            });
        }
    }

    // ------------------------------------------------------------------
    openList(domain = [], name = false) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || this.state.data.name,
            res_model: this.sectionModel,
            domain,
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    get sectionModel() {
        const rows = (this.state.data.recent || []).concat(this.state.data.pending_list || []);
        return rows.length ? rows[0].model : false;
    }

    openFullList() {
        this.action.doAction(this.state.data.action);
    }

    openRecord(model, resId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: resId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    backToHome() {
        this.action.doAction("bank_settlement.action_bank_settlement_home");
    }
}

registry.category("actions").add("bank_settlement_section", BankSettlementSection);
