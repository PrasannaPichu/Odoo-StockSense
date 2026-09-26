/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class StocksenseCommandCenter extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");

        this.state = useState({
            activeTab: "overview",
            metrics: {
                kpis: {},
                audit_integrity: { valid: true, total_blocks: 0 },
                recent_movements: [],
                critical_products: [],
                warehouse_stats: []
            },
            simProductId: null,
            simType: "delivery",
            simQty: 25,
            simResult: null,
            loading: true
        });

        onWillStart(async () => {
            await this.refreshData();
        });
    }

    async refreshData() {
        try {
            this.state.loading = true;
            const data = await this.rpc("/api/stocksense/dashboard/metrics", {});
            this.state.metrics = data;
            if (data.critical_products && data.critical_products.length > 0 && !this.state.simProductId) {
                this.state.simProductId = data.critical_products[0].id;
                this.runSimulator();
            }
        } catch (err) {
            console.error("Failed to load StockSense metrics:", err);
        } finally {
            this.state.loading = false;
        }
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    async runSimulator() {
        if (!this.state.simProductId) return;
        try {
            const res = await this.rpc("/api/stocksense/simulate", {
                product_id: parseInt(this.state.simProductId),
                scenario_type: this.state.simType,
                quantity: parseFloat(this.state.simQty)
            });
            if (res.success) {
                this.state.simResult = res.result;
            }
        } catch (err) {
            console.error("Simulation RPC failed:", err);
        }
    }
}

StocksenseCommandCenter.template = "stocksense.CommandCenter";
registry.category("actions").add("stocksense_command_center_view", StocksenseCommandCenter);
