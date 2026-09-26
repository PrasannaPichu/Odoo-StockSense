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
            productSearch: "",
            productHealthFilter: "all",
            warehouseFilter: "all",
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

    navigateToInventory(healthFilter = "all", warehouseFilter = "all") {
        this.state.productHealthFilter = healthFilter;
        if (warehouseFilter !== undefined) {
            this.state.warehouseFilter = warehouseFilter;
        }
        this.state.activeTab = "inventory";
    }

    navigateToAlerts() {
        this.state.activeTab = "intel";
    }

    navigateToTimeline() {
        this.state.activeTab = "timeline";
    }

    navigateToFlow() {
        this.state.activeTab = "flow";
    }

    setProductHealthFilter(filter) {
        this.state.productHealthFilter = filter;
    }

    setWarehouseFilter(whCode) {
        this.state.warehouseFilter = whCode;
    }

    onWarehouseFilterChange(ev) {
        this.state.warehouseFilter = ev.target.value;
    }

    onProductSearchInput(ev) {
        this.state.productSearch = (ev.target.value || "").toLowerCase().trim();
    }

    onGlobalSearch(ev) {
        const val = (ev.target.value || "").trim();
        this.state.productSearch = val.toLowerCase();
        if (val && this.state.activeTab === "overview") {
            this.state.activeTab = "inventory";
        }
    }

    clearProductSearch() {
        this.state.productSearch = "";
    }

    get filteredProducts() {
        const products = this.state.metrics.all_products || [];
        const healthFilter = this.state.productHealthFilter;
        const whFilter = this.state.warehouseFilter;
        const search = this.state.productSearch;

        return products.filter((p) => {
            if (healthFilter !== "all" && p.health_status !== healthFilter) {
                return false;
            }
            if (whFilter !== "all") {
                const matchesWhCode = p.warehouse_code === whFilter;
                const matchesWhName = p.warehouse_name === whFilter;
                const matchesWhId = p.warehouse_ids && p.warehouse_ids.includes(parseInt(whFilter));
                if (!matchesWhCode && !matchesWhName && !matchesWhId) {
                    return false;
                }
            }
            if (search) {
                const name = (p.name || "").toLowerCase();
                const sku = (p.sku || "").toLowerCase();
                const cat = (p.category_name || "").toLowerCase();
                if (!name.includes(search) && !sku.includes(search) && !cat.includes(search)) {
                    return false;
                }
            }
            return true;
        });
    }

    get productsRequiringAttention() {
        const products = this.state.metrics.all_products || [];
        return products.filter((p) => p.health_status === "critical" || p.health_status === "attention");
    }

    get operationalFocusItems() {
        const items = this.productsRequiringAttention;
        return [...items].sort((a, b) => {
            if (a.health_status === "critical" && b.health_status !== "critical") return -1;
            if (b.health_status === "critical" && a.health_status !== "critical") return 1;
            return a.stock - b.stock;
        }).slice(0, 3);
    }

    get recentActivityEvents() {
        const list = this.state.metrics.recent_movements || [];
        return list.slice(0, 5);
    }

    formatCurrency(val) {
        return Number(val || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    formatNumber(val) {
        return Number(val || 0).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    getStockBarWidth(stock, maxThreshold) {
        const max = maxThreshold && maxThreshold > 0 ? maxThreshold : 100;
        const pct = (Number(stock || 0) / max) * 100;
        return Math.min(100, Math.max(0, Math.round(pct)));
    }

    getMinMarkerPos(minThreshold, maxThreshold) {
        const max = maxThreshold && maxThreshold > 0 ? maxThreshold : 100;
        const pct = (Number(minThreshold || 0) / max) * 100;
        return Math.min(100, Math.max(0, Math.round(pct)));
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

    testInSimulator(productId) {
        this.state.simProductId = productId;
        this.state.activeTab = "simulator";
        this.runSimulator();
    }

    // Direct Odoo Action Navigation
    openProductForm(productId) {
        this.actionService.doAction({
            name: "Product Master",
            type: "ir.actions.act_window",
            res_model: "stocksense.product",
            res_id: productId,
            views: [[false, "form"]],
        });
    }

    openProductLedger(productId, productName) {
        this.actionService.doAction({
            name: `Stock Ledger: ${productName || 'SKU'}`,
            type: "ir.actions.act_window",
            res_model: "stocksense.stock.ledger",
            view_mode: "tree,form",
            domain: [["product_id", "=", productId]],
        });
    }

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
