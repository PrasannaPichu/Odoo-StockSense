/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class StocksenseCommandCenter extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.actionService = useService("action");

        this.state = useState({
            activeTab: "overview",
            metrics: {
                kpis: {},
                movement_overview: {},
                operational_intelligence: {
                    critical_count: 0,
                    attention_count: 0,
                    anomalies_count: 0,
                    low_stock_count: 0,
                    anomalies: [],
                    active_alerts: []
                },
                health_distribution: {},
                audit_integrity: { valid: true, total_blocks: 0, blocks: [] },
                recent_movements: [],
                critical_products: [],
                all_products: [],
                warehouse_stats: []
            },
            simProductId: null,
            simType: "delivery",
            simQty: 25,
            simResult: null,
            expandedBlockId: null,
            loading: true,
            errorMessage: null
        });

        onWillStart(async () => {
            await this.refreshData();
        });
    }

    async refreshData() {
        try {
            this.state.loading = true;
            this.state.errorMessage = null;
            const data = await this.rpc("/api/stocksense/dashboard/metrics", {});
            this.state.metrics = data;
            
            // Default simulator selection to first critical product or first product
            if (!this.state.simProductId) {
                if (data.critical_products && data.critical_products.length > 0) {
                    this.state.simProductId = data.critical_products[0].id;
                } else if (data.all_products && data.all_products.length > 0) {
                    this.state.simProductId = data.all_products[0].id;
                }
                if (this.state.simProductId) {
                    await this.runSimulator();
                }
            }
        } catch (err) {
            console.error("Failed to load StockSense metrics:", err);
            this.state.errorMessage = "Failed to communicate with StockSense backend. Please ensure Odoo and PostgreSQL are running.";
        } finally {
            this.state.loading = false;
        }
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    toggleBlockPayload(blockId) {
        if (this.state.expandedBlockId === blockId) {
            this.state.expandedBlockId = null;
        } else {
            this.state.expandedBlockId = blockId;
        }
    }

    async onSimProductChange(ev) {
        this.state.simProductId = parseInt(ev.target.value);
        await this.runSimulator();
    }

    async onSimTypeChange(ev) {
        this.state.simType = ev.target.value;
        await this.runSimulator();
    }

    async onSimQtyChange(ev) {
        this.state.simQty = parseFloat(ev.target.value);
        await this.runSimulator();
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
            this.notification.add("Simulation execution failed", { type: "danger" });
        }
    }

    // Direct Odoo Action Navigation
    openCriticalProducts() {
        this.actionService.doAction({
            name: "Critical Risk SKUs",
            type: "ir.actions.act_window",
            res_model: "stocksense.product",
            view_mode: "tree,form",
            domain: [["health_status", "=", "critical"]],
        });
    }

    openAttentionProducts() {
        this.actionService.doAction({
            name: "Attention Required SKUs",
            type: "ir.actions.act_window",
            res_model: "stocksense.product",
            view_mode: "tree,form",
            domain: [["health_status", "=", "attention"]],
        });
    }

    openAlertsList(severity = null) {
        const domain = [["state", "=", "new"]];
        if (severity) {
            domain.push(["severity", "=", severity]);
        }
        this.actionService.doAction({
            name: "Active Inventory Alerts",
            type: "ir.actions.act_window",
            res_model: "stocksense.inventory.alert",
            view_mode: "tree,form",
            domain: domain,
        });
    }

    openReceiptsList() {
        this.actionService.doAction({
            name: "Inbound Goods Receipts",
            type: "ir.actions.act_window",
            res_model: "stocksense.receipt",
            view_mode: "tree,form",
            domain: [["state", "in", ["draft", "confirmed"]]],
        });
    }

    openDeliveriesList() {
        this.actionService.doAction({
            name: "Outbound Deliveries",
            type: "ir.actions.act_window",
            res_model: "stocksense.delivery",
            view_mode: "tree,form",
            domain: [["state", "in", ["draft", "confirmed", "assigned"]]],
        });
    }

    openLedgerHistory() {
        this.actionService.doAction({
            name: "Stock Ledger History",
            type: "ir.actions.act_window",
            res_model: "stocksense.stock.ledger",
            view_mode: "tree,form",
        });
    }
}

StocksenseCommandCenter.template = "stocksense.CommandCenter";
registry.category("actions").add("stocksense_command_center_view", StocksenseCommandCenter);
