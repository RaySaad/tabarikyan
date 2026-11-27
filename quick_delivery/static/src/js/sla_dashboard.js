/** @odoo-module **/
import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
// خدمة "rpc" أُزيلت من أودو 19 (لا تسجيل لها في web ولا استعمال لها في
// الكود الأساسي)، وكان useService("rpc") يُسقط الداش بورد لحظة فتحه -
// وهي الشاشة الرئيسية للموديول. البديل هو هذه الدالة المُصدَّرة مباشرةً.
import { rpc } from "@web/core/network/rpc";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class QuickSlaDashboard extends Component {
    static props = { ...standardActionServiceProps };

    setup() {
        this.rpc = rpc;
        this.notification = useService("notification");
        this.busService = this.env.services.bus_service;
        this.mapRef = useRef("liveMapContainer");
        this.map = null;
        this.markersLayer = null;

        // نطاق الغرفة: شركة واحدة أو الكل. يأتي من سياق الإجراء حين
        // تُفتح من مربّع السوبرماركت في الصفحة الرئيسية.
        const context = (this.props.action && this.props.action.context) || {};
        this.state = useState({
            kpis: { active_count: 0, unassigned_count: 0, online_drivers: 0, busy_drivers: 0, delivered_today: 0, total_cod_today: 0 },
            orders: [],
            drivers: [],
            scope: { client_id: context.client_id || false, client_name: "", clients: [] },
        });

        onWillStart(async () => {
            await this._loadLeafletAssets();
            await this.loadData();
            this.busService.addChannel("quick_delivery_channel");
            this.busService.addEventListener("notification", () => this.loadData());
            this.timer = setInterval(() => this.loadData(), 10000);
        });

        onMounted(() => {
            this._initMap();
            this._renderMapMarkers();
        });

        onWillUnmount(() => {
            clearInterval(this.timer);
            if (this.map) this.map.remove();
        });
    }

    async _loadLeafletAssets() {
        if (!document.getElementById("leaflet-css")) {
            const link = document.createElement("link");
            link.id = "leaflet-css";
            link.rel = "stylesheet";
            link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
            document.head.appendChild(link);
        }
        if (!window.L) {
            await new Promise((resolve) => {
                const script = document.createElement("script");
                script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
                script.onload = resolve;
                document.body.appendChild(script);
            });
        }
    }

    _initMap() {
        if (!window.L || !this.mapRef.el) return;
        this.map = window.L.map(this.mapRef.el).setView([24.7136, 46.6753], 11);
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "&copy; OpenStreetMap"
        }).addTo(this.map);
        this.markersLayer = window.L.layerGroup().addTo(this.map);
    }

    _renderMapMarkers() {
        if (!this.map || !this.markersLayer || !window.L) return;
        this.markersLayer.clearLayers();

        this.state.drivers.forEach(drv => {
            if (drv.status !== 'offline' && drv.lat && drv.lng) {
                // المندوب مشترك بين الشركات: من هو في مهمة لشركة أخرى
                // يبقى ظاهراً - فالطاقة المتاحة نصف فائدة الخريطة -
                // لكنه باهت حتى لا يختلط عمل الشركات.
                const other = drv.busy_for_other;
                const color = other ? '#adb5bd'
                    : (drv.status === 'online' ? '#198754' : '#0d6efd');
                const busyNote = drv.busy_for
                    ? `<br/>في مهمة لـ: ${drv.busy_for}` : '';
                const marker = window.L.circleMarker([drv.lat, drv.lng], {
                    radius: other ? 7 : 9,
                    fillColor: color,
                    color: '#fff',
                    weight: 2,
                    fillOpacity: other ? 0.55 : 0.95
                }).bindPopup(`<b>مندوب: ${drv.name}</b><br/>الحالة: ${drv.status === 'online' ? 'متاح' : 'في مهمة'}${busyNote}<br/>عهدة COD: ${drv.cod_balance} ر.س`);
                this.markersLayer.addLayer(marker);
            }
        });

        this.state.orders.forEach(ord => {
            if (ord.store_lat && ord.store_lng) {
                const storeMarker = window.L.circleMarker([ord.store_lat, ord.store_lng], {
                    radius: 8,
                    fillColor: '#fd7e14',
                    color: '#000',
                    weight: 1.5,
                    fillOpacity: 0.9
                }).bindPopup(`<b>فرع: ${ord.store_name}</b><br/>طلب: ${ord.name}`);
                this.markersLayer.addLayer(storeMarker);
            }
            if (ord.customer_lat && ord.customer_lng) {
                const custMarker = window.L.circleMarker([ord.customer_lat, ord.customer_lng], {
                    radius: 7,
                    fillColor: '#dc3545',
                    color: '#fff',
                    weight: 1.5,
                    fillOpacity: 0.9
                }).bindPopup(`<b>عميل: ${ord.customer_name}</b><br/>متبقي: ${ord.remaining_minutes} د`);
                this.markersLayer.addLayer(custMarker);
            }
        });
    }

    async onManualAssignChange(orderId, ev) {
        const driverId = ev.target.value;
        if (!driverId) return;
        // الخادم يرفض الآن التوزيع بعد الاستلام، أو لمستخدم ليس مندوباً،
        // أو لمن أُسند له طلب آخر - فالرد يُقرأ ويُعرض بدل تجاهله.
        const res = await this.rpc("/api/v1/qcommerce/manual_assign", {
            order_id: orderId,
            driver_id: driverId
        });
        if (res && res.status === "error") {
            this.notification.add(res.error || "تعذّر إسناد المندوب", {
                type: "danger",
            });
        }
        await this.loadData();
    }

    async loadData() {
        const res = await this.rpc("/api/v1/qcommerce/dashboard", {
            client_id: this.state.scope.client_id || null,
        });
        if (res) {
            this.state.kpis = res.kpis;
            this.state.orders = res.orders;
            this.state.drivers = res.drivers || [];
            if (res.scope) {
                this.state.scope = res.scope;
            }
            this._renderMapMarkers();
        }
    }

    /** التنقّل بين الشركات بلا رجوع إلى الصفحة الرئيسية. */
    async onScopeChange(ev) {
        const value = ev.target.value;
        this.state.scope.client_id = value ? parseInt(value, 10) : false;
        await this.loadData();
        // الخريطة تُعاد إلى مدى السعودية حين يتغيّر النطاق، وإلا بقيت
        // على تقريب شركة سابقة لا دبابيس لها الآن.
        if (this.map) {
            this.map.setView([24.7136, 46.6753], 11);
        }
    }
}
QuickSlaDashboard.template = "quick_delivery.SlaDashboardTemplate";
registry.category("actions").add("quick_delivery.sla_dashboard", QuickSlaDashboard);
