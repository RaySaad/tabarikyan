/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * الصفحة الرئيسية لتطبيق السداد البنكي: أقسامه أيقوناتٍ كصفحة تطبيقات
 * أودو. البطاقات تأتي من الخادم محسوبةً بصلاحية المستخدم - فلا تُبنى
 * هنا قائمة ثابتة تُخفى بالواجهة.
 */
export class BankSettlementHome extends Component {
    static template = "bank_settlement.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, data: null });

        onWillStart(async () => {
            this.state.data = await this.orm.call(
                "bank.settlement.dashboard", "get_sections", []);
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

    /** لوحة القسم إجراء عميل واحد يخدم الأقسام كلها عبر السياق. */
    openSection(key) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "bank_settlement_section",
            name: this.sectionName(key),
            context: { section: key },
        });
    }

    sectionName(key) {
        const section = (this.state.data.sections || []).find((s) => s.key === key);
        return section ? section.name : "";
    }

    openExtra(xmlid) {
        this.action.doAction(xmlid);
    }
}

registry.category("actions").add("bank_settlement_home", BankSettlementHome);
