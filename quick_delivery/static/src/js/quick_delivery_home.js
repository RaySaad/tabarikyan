/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * الصفحة الرئيسية للتوصيل الفوري: السوبرماركتات أيقوناتٍ، بنفس هوية
 * مركز السداد البنكي في هذا المستودع.
 *
 * المربّعات ليست ثابتة كما هناك: تأتي من الخادم محسوبةً بصلاحية
 * المستخدم، فإضافة بندة تُضيف أيقونتها وحدها بلا تعديل كود.
 */
export class QuickDeliveryHome extends Component {
    static template = "quick_delivery.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, data: null });

        onWillStart(async () => {
            this.state.data = await this.orm.call(
                "quick.delivery.home", "get_home", []);
            this.state.loading = false;
        });
    }

    money(value) {
        const amount = (value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
        const currency = (this.state.data && this.state.data.currency) || {};
        return currency.symbol ? `${amount} ${currency.symbol}` : amount;
    }

    /**
     * ضغط السوبرماركت يفتح **غرفة عملياته هو**: خريطته وطلباته
     * ومؤقّتاته. كما في مركز السداد البنكي حيث يفتح المربّع لوحة
     * القسم لا قائمة سجلات.
     */
    openMerchant(merchant) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "quick_delivery.sla_dashboard",
            name: merchant.name,
            context: { client_id: merchant.id },
        });
    }

    /** قائمة طلبات الشركة - زرٌّ ثانٍ لمن يريد السجل لا الخريطة. */
    openMerchantOrders(merchant, ev) {
        ev.stopPropagation();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: merchant.name,
            res_model: "quick.delivery.order",
            views: [[false, "list"], [false, "form"]],
            domain: [["client_id", "=", merchant.id]],
            context: { search_default_group_state: 1 },
        });
    }

    openExtra(xmlid) {
        this.action.doAction(xmlid);
    }
}

registry.category("actions").add("quick_delivery_home", QuickDeliveryHome);
