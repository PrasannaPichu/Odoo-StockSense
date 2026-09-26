# StockSense — Master Product Requirements Document (PRD) & Technical Specification

**Project:** StockSense — Intelligent, Event-Driven Inventory Management and Operational Decision Support System  
**Hackathon:** Odoo x GCET Hyderabad Hackathon 2026  
**Repository:** `Odoo-StockSense`  
**Target Branch:** `main`  
**System Motto:** *"Don't just record inventory. Understand what is happening to inventory."*  

---

## 1. Executive Summary & Objective

Modern enterprise supply chains and warehouse operations suffer from a fundamental disconnect: traditional ERPs act as passive digital ledgers. They record when stock is received, transferred, or shipped, but they fail to actively interpret the operational pulse of the warehouse. Discrepancies are discovered days or weeks later during manual audits, stock-outs trigger panic re-orders, and managers lack real-time foresight into how operational shifts cascade through downstream logistics.

**StockSense** transforms the Odoo inventory paradigm from a passive transactional record into an **active, event-driven operational decision-support system**. Built natively on Odoo (Python, OWL, PostgreSQL), integrated with an asynchronous **Apache Kafka** event streaming backbone, and powered by an **Explainable Inventory Health Engine**, StockSense guarantees:
1. **Absolute Financial & Physical Determinism:** PostgreSQL remains the ACID-compliant, single source of transactional truth.
2. **Real-Time Operational Decoupling:** Every warehouse operation (Receipt, Delivery, Transfer, Adjustment) emits structured events to Kafka topic streams partitioned by `product_id`.
3. **Continuous Intelligence & Explainability:** Dedicated consumer micro-services process streaming telemetry to evaluate inventory health scores, detect operational anomalies (e.g., erratic adjustments, phantom depletion, velocity spikes), and generate human-readable causal explanations—not black-box numbers.
4. **Predictive Scenario Simulation:** An isolated "What-If" simulator enables warehouse supervisors to test hypotheticals (e.g., bulk dispatch, supplier delays) without mutating transactional state.
5. **Tamper-Evident Integrity:** A cryptographic SHA-256 hash-chained ledger ensures that every inventory transition is forensically verifiable and immutable.
6. **Executive Command Center:** A modern, multi-palette, responsive OWL frontend featuring live KPI cards, interactive warehouse flow diagrams, chronological stock timelines, and multi-dimensional filtering.

---

## 2. Core Development Principles & Non-Goals

### 2.1 Core Principles
1. **Correctness Before Complexity:** Stock ledger balances must always equal the physical sum of quants: $\text{Balance}_{t} = \text{Balance}_{t-1} \pm \Delta \text{Qty}$.
2. **PostgreSQL as the Transactional Source of Truth:** Stock is never committed in Kafka first. Transactions commit in PostgreSQL; event emission follows the transactional outbox/post-commit hook.
3. **Deterministic Intelligence:** Explainability is first-class. If an item is flagged as `CRITICAL`, the system outputs exact contributing factors (e.g., *Current stock (14) $\le$ Min threshold (50)*, *Outbound velocity (+340% over 7d baseline)*, *Zero pending POs*).
4. **Zero State Mutation in Simulations:** What-if calculations execute purely in-memory using cloned state snapshots; they never write to stock quants or ledger tables.
5. **Fail-Safe Event Streaming:** If Kafka brokers become temporarily unreachable, Odoo transactions must succeed while outbox events queue locally with retry policies.
6. **Zero Fabricated AI/ML:** Statistical methods (Z-scores, moving average baselines, interquartile range) are clearly labeled as statistics. Machine learning models (e.g., Random Forest or Isolation Forests) are applied only with valid training distributions.

### 2.2 Strict Non-Goals
- No standalone React/Vue/Node.js SPAs outside Odoo; all frontend UI is implemented natively within Odoo's WebClient and OWL (Odoo Web Library) framework.
- No NoSQL/MongoDB databases; relational integrity and foreign keys are paramount.
- No blockchain or crypto-tokens; cryptographic auditability is achieved via transparent SHA-256 hash chaining.
- No silent negative inventory unless specifically enabled under an authorized override policy.

---

## 3. Technology Stack & Component Architecture

```
                                  STOCKSENSE
                                      |
                    +-----------------+-----------------+
                    |                                   |
             ODOO WEB (OWL)                        REST API
         Command Center / Views               Integrations / Webhooks
                    |                                   |
                    +-----------------+-----------------+
                                      |
                           CORE BUSINESS LOGIC
                    (Products, Warehouses, Quants,
                     Receipts, Deliveries, Transfers,
                              Adjustments)
                                      |
                     +----------------+----------------+
                     |                                 |
           PostgreSQL (ACID)                    Apache Kafka
         Single Source of Truth               Event Streaming Backbone
                     |                                 |
                     |         +-----------------------+-----------------------+
                     |         |                       |                       |
                     |     Analytics Consumer    Alert Consumer         Audit Consumer
                     |     (Pandas / Metrics)  (Thresholds / Risk)   (Hash-Chain Verifier)
                     |         |                       |                       |
                     +---------+-----------------------+-----------------------+
                                               |
                                     INVENTORY INTELLIGENCE
                                               |
                       +-----------------------+-----------------------+
                       |                       |                       |
               Health Engine             Anomaly Engine           What-If Simulator
             (Rule/Factor Based)       (Statistical/Z-Score)      (In-Memory Sandboxed)
                       |                       |                       |
                       +-----------------------+-----------------------+
                                               |
                                    EXPLAINABILITY ENGINE
                               (Human-Readable Diagnostics)
                                               |
                                    DECISION SUPPORT & UI
```

| Layer | Technologies / Libraries | Purpose |
|---|---|---|
| **Core Framework** | Odoo 17/18 / Python 3.12 / Werkzeug | ORM, Business Logic, Security Groups, Actions, XML Views |
| **Database** | PostgreSQL 16/17 | Normalized Schema, Foreign Keys, Unique Indexes, Constraints |
| **Event Streaming** | Apache Kafka / `confluent-kafka` or `kafka-python` | Asynchronous decoupled event distribution, topic partitioning |
| **Frontend / UI** | JavaScript (ES6+), OWL Components, CSS3, Chart.js / SVG | Reactive Command Center, Timelines, Warehouse Flow, KPIs |
| **Analytics Engine** | Python, Pandas, NumPy, SciPy | Rolling window analytics, consumption volatility, stock velocity |
| **Security & Audit** | Python `hashlib` (SHA-256) | Hash-chained audit logs, role-based access rules (ACLs/IR Rules) |
| **Testing** | Odoo `TransactionCase`, Python `unittest`, Mock | End-to-end business rule verification, ledger invariant testing |

---

## 4. Core Relational Data Model

All models inherit from Odoo's `models.Model` and adhere to relational normalization standards.

```
 +--------------------+       +----------------------+       +----------------------+
 | stocksense.warehouse|<----*|  stocksense.location |<-----*|   stocksense.quant   |
 +--------------------+       +----------------------+       +----------------------+
                                                                        |
                               +---------------------+                  |
                               |  stocksense.product |*-----------------+
                               +---------------------+                  |
                                         |                              |
      +----------------------------------+------------------------------+
      |                  |                               |
      v                  v                               v
+--------------+   +---------------+              +--------------+
|receipt.line  |   |delivery.line  |              |ledger.entry  |
+--------------+   +---------------+              +--------------+
      |                  |                               |
      v                  v                               v
+--------------+   +---------------+              +--------------+
|receipt       |   |delivery       |              |audit.trail   |
+--------------+   +---------------+              +--------------+
```

### 4.1 Entity Specifications

1. **`stocksense.warehouse`**
   - `id` (PK, Integer)
   - `name` (Char, required)
   - `code` (Char(5), unique, required)
   - `address` (Text)
   - `active` (Boolean, default=True)
   - `location_ids` (One2many -> `stocksense.location`)

2. **`stocksense.location`**
   - `id` (PK, Integer)
   - `name` (Char, required)
   - `complete_name` (Char, computed hierarchical name)
   - `warehouse_id` (Many2one -> `stocksense.warehouse`, ondelete='cascade')
   - `parent_id` (Many2one -> `stocksense.location`)
   - `usage` (Selection: `internal`, `supplier`, `customer`, `inventory_loss`, `transit`)
   - `barcode` (Char, indexed)

3. **`stocksense.product.category`**
   - `id` (PK, Integer)
   - `name` (Char, required)
   - `parent_id` (Many2one -> `stocksense.product.category`)

4. **`stocksense.product`**
   - `id` (PK, Integer)
   - `name` (Char, required, indexed)
   - `default_code` / `sku` (Char, unique, required, indexed)
   - `category_id` (Many2one -> `stocksense.product.category`, required)
   - `uom_id` (Many2one -> `uom.uom`, required)
   - `standard_price` (Monetary/Float, cost)
   - `list_price` (Monetary/Float, sales price)
   - `min_stock_threshold` (Float, default=10.0)
   - `max_stock_threshold` (Float, default=100.0)
   - `total_stock` (Float, computed store=True)
   - `health_status` (Selection: `healthy`, `attention`, `critical`, computed)
   - `active` (Boolean, default=True)

5. **`stocksense.quant`** (Real-time physical stock snapshot)
   - `id` (PK, Integer)
   - `product_id` (Many2one -> `stocksense.product`, required, indexed)
   - `location_id` (Many2one -> `stocksense.location`, required, indexed)
   - `quantity` (Float, required, default=0.0)
   - `reserved_quantity` (Float, default=0.0)
   - *Constraint:* Unique `(product_id, location_id)`

6. **`stocksense.stock.ledger`** (Immutable Double-Entry Ledger)
   - `id` (PK, Integer)
   - `name` (Char, Sequence e.g. `LEDG/2026/00001`)
   - `date` (Datetime, required, default=now, indexed)
   - `product_id` (Many2one -> `stocksense.product`, required, indexed)
   - `location_src_id` (Many2one -> `stocksense.location`)
   - `location_dest_id` (Many2one -> `stocksense.location`)
   - `quantity_change` (Float, signed)
   - `balance_before` (Float, required)
   - `balance_after` (Float, required)
   - `operation_type` (Selection: `receipt`, `delivery`, `internal_transfer`, `adjustment`)
   - `reference_document` (Char, indexed e.g. `REC/0001`, `DEL/0004`, `ADJ/0002`)
   - `user_id` (Many2one -> `res.users`, required)
   - `notes` (Text)

7. **`stocksense.receipt` & `stocksense.receipt.line`**
   - States: `draft` -> `confirmed` -> `validated` -> `cancelled`
   - Header fields: `name`, `partner_id` (Supplier), `warehouse_id`, `destination_location_id`, `date`, `state`
   - Line fields: `product_id`, `quantity_expected`, `quantity_received`, `uom_id`

8. **`stocksense.delivery` & `stocksense.delivery.line`**
   - States: `draft` -> `confirmed` -> `assigned` -> `validated` -> `cancelled`
   - Header fields: `name`, `partner_id` (Customer), `warehouse_id`, `source_location_id`, `date`, `state`
   - Line fields: `product_id`, `quantity_requested`, `quantity_delivered`, `uom_id`

9. **`stocksense.transfer` & `stocksense.transfer.line`**
   - States: `draft` -> `in_transit` -> `completed` -> `cancelled`
   - Header fields: `name`, `source_warehouse_id`, `dest_warehouse_id`, `source_location_id`, `dest_location_id`, `state`
   - Line fields: `product_id`, `quantity`

10. **`stocksense.adjustment` & `stocksense.adjustment.line`**
    - Header fields: `name`, `warehouse_id`, `location_id`, `reason` (`damage`, `missing`, `count_error`, `expired`, `other`), `date`, `state`
    - Line fields: `product_id`, `recorded_qty`, `counted_qty`, `discrepancy_qty`

11. **`stocksense.inventory.alert`**
    - `product_id`, `warehouse_id`, `current_quantity`, `threshold`, `severity` (`info`, `warning`, `critical`), `reason`, `state` (`new`, `acknowledged`, `resolved`), `detected_at`

12. **`stocksense.audit.trail`**
    - `id` (PK, Integer)
    - `sequence_number` (Integer, indexed, strictly sequential)
    - `timestamp` (Datetime, required)
    - `event_type` (Char, required)
    - `record_reference` (Char, required)
    - `payload_json` (Text, normalized JSON)
    - `previous_hash` (Char(64), required)
    - `current_hash` (Char(64), required)
    - `is_verified` (Boolean, default=True)

---

## 5. End-to-End Operational Workflows

### 5.1 Receipt Flow
1. Operator creates a Receipt picking document for a verified Supplier.
2. Selects destination Warehouse / Location (defaults to `WH/Stock`).
3. Populates product lines with received quantities.
4. Clicks **Validate**:
   - Atomic database transaction initiated.
   - Increases `stocksense.quant` for `(product_id, destination_location_id)`.
   - Creates a `stocksense.stock.ledger` entry: `quantity_change = +qty`, records previous & new balance.
   - Emits Kafka event: `RECEIPT_VALIDATED` to `stocksense.inventory.events`.
   - Triggers `stocksense.audit.trail` hash-chained record.
   - Transaction commits.

### 5.2 Delivery Flow
1. Operator creates a Delivery Order for a Customer with requested product lines.
2. Selects source Warehouse / Location.
3. System verifies stock availability across internal locations.
4. Clicks **Validate**:
   - Availability check: ensures $\text{Available Stock} \ge \text{Requested Qty}$. If insufficient, aborts with a descriptive user validation error.
   - Decreases `stocksense.quant` for `(product_id, source_location_id)`.
   - Creates a `stocksense.stock.ledger` entry: `quantity_change = -qty`.
   - Evaluates real-time threshold: triggers `LOW_STOCK_DETECTED` if new balance $\le$ `min_stock_threshold`.
   - Emits Kafka event: `DELIVERY_VALIDATED`.
   - Triggers audit trail update.

### 5.3 Internal Transfer Flow
1. Moves goods between internal locations: `Warehouse A/Rack 1` $\rightarrow$ `Warehouse B/Rack 3`.
2. Total company-wide inventory balance remains invariant ($\Delta = 0$).
3. Decrements source quant; increments destination quant.
4. Creates two mirrored ledger entries or a single transfer ledger reference tracking source and destination.
5. Emits `TRANSFER_COMPLETED` event.

### 5.4 Inventory Adjustment Flow
1. Physical cycle counts often reveal differences ($\text{Counted} - \text{Recorded} = \Delta$).
2. Operator must mandate an adjustment reason: `damage`, `theft/missing`, `counting_error`, `spoilage`.
3. Validating updates the quant directly to `Counted Qty`.
4. Ledger records $\Delta$ against virtual location `Inventory adjustment/loss`.
5. Emits `STOCK_ADJUSTED` event. If repeated adjustments occur for the same SKU, an anomaly rule is flagged.

---

## 6. Event Streaming Architecture (Kafka Integration)

### 6.1 Topics & Schema Governance

| Topic Name | Partition Key | Retention | Description |
|---|---|---|---|
| `stocksense.inventory.events` | `product_id` (String) | 7 days | Primary operational ledger events (receipts, deliveries, transfers, adjustments) |
| `stocksense.inventory.alerts` | `product_id` (String) | 30 days | Real-time threshold breaches, rapid depletion alerts |
| `stocksense.inventory.analytics` | `warehouse_id` (String) | 7 days | Periodic aggregations, velocity updates, throughput metrics |
| `stocksense.inventory.audit` | `sequence_number` (String) | Permanent | Cryptographic hash-chain block confirmations |

### 6.2 Standard Event Payload Schema

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440000",
  "event_type": "RECEIPT_VALIDATED",
  "version": "1.0",
  "timestamp": "2026-09-26T10:15:30.123456Z",
  "producer": "odoo_stocksense_core",
  "payload": {
    "reference": "REC/2026/00042",
    "product_id": 142,
    "product_sku": "STEEL-ROD-01",
    "product_name": "High-Tensile Steel Rod 10mm",
    "warehouse_id": 1,
    "warehouse_code": "WH-MAIN",
    "location_id": 4,
    "location_name": "WH-MAIN/Stock/Rack-B",
    "quantity_delta": 50.0,
    "uom": "Units",
    "balance_before": 100.0,
    "balance_after": 150.0,
    "user_id": 7,
    "user_name": "Warehouse Supervisor"
  },
  "metadata": {
    "trace_id": "trc_9a8b7c6d5e4f",
    "client_ip": "192.168.1.104"
  }
}
```

### 6.3 Producer Resilience & Fail-Safe Delivery
- **Transactional Outbox / Graceful Fallback:** If the Kafka broker is down or unreachable, events are recorded in an internal PostgreSQL table `stocksense.event.outbox` with status `pending`.
- A background cron/runner flushes queued outbox events upon broker reconnection, guaranteeing **at-least-once delivery** without halting core warehouse operations.
- Partitioning by `product_id` guarantees strict chronological event ordering per individual SKU.

---

## 7. Inventory Intelligence & Decision Support Engines

### 7.1 Explainable Inventory Health Engine

Rather than relying on unexplainable black-box scores, StockSense computes a composite Health Index based on four deterministic sub-scores:

$$\text{Health Index} = w_1 S_{\text{stock}} + w_2 S_{\text{velocity}} + w_3 S_{\text{pipeline}} + w_4 S_{\text{adjustment}}$$

Where:
1. **$S_{\text{stock}}$ (Stock Level Ratio):**
   $$\text{Ratio} = \frac{\text{Current Stock}}{\text{Minimum Threshold}}$$
   - Ratio $\ge 1.5 \implies 100\%$ (Healthy)
   - $1.0 \le \text{Ratio} < 1.5 \implies 75\%$ (Adequate)
   - $0.5 \le \text{Ratio} < 1.0 \implies 35\%$ (Attention)
   - $\text{Ratio} < 0.5 \implies 0\%$ (Critical)

2. **$S_{\text{velocity}}$ (Depletion Velocity Factor):** Days of Inventory Remaining (DIR):
   $$\text{DIR} = \frac{\text{Current Stock}}{\text{Average Daily Outbound (last 14 days)}}$$
   - $\text{DIR} \ge 14 \text{ days} \implies 100\%$
   - $7 \le \text{DIR} < 14 \implies 60\%$
   - $\text{DIR} < 7 \text{ days} \implies 20\%$

3. **$S_{\text{pipeline}}$ (Inbound Replenishment Coverage):** Evaluates confirmed pending receipts due within the depletion horizon.

4. **$S_{\text{adjustment}}$ (Stability Metric):** Deducts points for repeated negative adjustments (damage/shrinkage) within the past 30 days.

#### Categorical States:
- **`HEALTHY`** (Score $\ge 75$): Normal operations, stock stable.
- **`ATTENTION`** (Score $45 - 74$): Approaching reorder point or elevated consumption.
- **`CRITICAL`** (Score $< 45$): Stock-out imminent or severe discrepancy detected.

#### Human-Readable Explainability Breakdown:
Every score card provides bulleted causal diagnostics:
- *Current stock (18 units) is 32 units below minimum threshold (50).*
- *Outbound velocity has surged by 45% over the 14-day baseline.*
- *No confirmed supplier receipts scheduled within the next 5 days.*
- *2 damage adjustments logged this week (-8 units total).*

---

### 7.2 Anomaly Detection Engine

Detects abnormal behavior using statistical rules and historical deviation:
1. **Sudden Outflow Surge (Z-Score):**
   $$Z = \frac{Q_{\text{delivery}} - \mu_{30}}{\sigma_{30}}$$
   If $Z > 3.0$, flag as an anomalous outbound spike.
2. **Frequent Stock Write-Downs:** SKU adjusted $\ge 3$ times within a rolling 7-day window flags a potential shrinkage/loss anomaly.
3. **Ghost Inflow:** Large receipt validated with no corresponding purchase order reference.
4. **Velocity Reversal:** Dead stock (zero movements in 60 days) experiencing an abrupt large withdrawal.

---

### 7.3 What-If Inventory Simulator (Sandboxed In-Memory Engine)

Warehouse managers can evaluate hypothetical scenarios without risking transactional corruption:
- **Scenario Types:**
  - *Bulk Delivery Simulation:* "What happens if client Acme orders 250 units tomorrow?"
  - *Supplier Delay Simulation:* "What happens if Receipt REC/002 is delayed by 10 days?"
  - *Multi-Location Rebalance:* "What happens if we move 40 units from WH-Central to WH-North?"
- **Safety Mechanism:** The simulator runs entirely in Python memory. It queries the current database quants, clones the state dictionary, applies mathematical transformations, evaluates the Health Engine on the hypothetical state, and returns:
  - Projected final balance.
  - Anticipated stock-out date.
  - Resulting Health Status (`HEALTHY` $\rightarrow$ `CRITICAL`).
  - Required safety order quantity.

---

## 8. Tamper-Evident Hash-Chained Audit Trail

To satisfy forensic supply chain compliance and auditability:
1. Genesis Block initialized with:
   $$\text{Hash}_0 = \text{SHA256}(\text{"STOCKSENSE\_GENESIS\_2026"})$$
2. For each transaction $i \ge 1$:
   $$\text{Payload}_i = \text{JSON}(\text{sort\_keys=True}, \{\text{id}, \text{timestamp}, \text{event}, \text{ref}, \text{user}, \text{qty}, \Delta\})$$
   $$\text{Current Hash}_i = \text{SHA256}(\text{Payload}_i + \text{Previous Hash}_{i-1})$$
3. Verification routine traverses the chain: if any past database row is altered (e.g. quantity changed via raw SQL), the hash chain breaks at block $k$, immediately flagging tampering.

---

## 9. Modern Frontend & OWL Command Center

The UI/UX is built to wow hackathon evaluators with high visual hierarchy, responsiveness, and executive clarity:

1. **KPI Header Strip:**
   - Total Active SKUs
   - Total Asset Valuation ($)
   - Critical Stock-Out Alerts
   - Inbound Shipments in Transit
   - System Audit Integrity Status (Green Check / Hash Chain Valid)
2. **Interactive Stock Flow Map:** SVG/OWL visualization showing live directional arrows from Suppliers $\rightarrow$ Central Warehouse $\rightarrow$ Secondary Locations $\rightarrow$ Customers.
3. **Stock Health Heatmap:** Color-coded inventory matrix (Emerald Green = Healthy, Amber Yellow = Attention, Crimson Red = Critical).
4. **Chronological Interactive Timeline:** Vertical event feed with filtering by SKU, Operation Type, and Operator.
5. **Embedded What-If Simulator Panel:** Slider-driven hypotheticals with dynamic comparison charts.

---

## 10. Implementation & Phased Execution Plan

- **Phase 0:** Master PRD & Repository Documentation (Verified & Pushed to `main`)
- **Phase 1:** Odoo Module Scaffold & Manifest (`odoo_stocksense`)
- **Phase 2:** Core Relational Database Models (Warehouses, Locations, Products, Categories, Quants)
- **Phase 3:** Stock Ledger Engine & Invariant Verification
- **Phase 4:** Operational Flows (Receipts, Deliveries, Transfers, Adjustments)
- **Phase 5:** Kafka Producer Integration & Resilient Outbox
- **Phase 6:** Kafka Consumers (Analytics, Alerting, Audit)
- **Phase 7:** Explainable Inventory Health Engine
- **Phase 8:** Statistical Anomaly Detection Engine
- **Phase 9:** Sandboxed What-If Simulator
- **Phase 10:** Tamper-Evident Cryptographic Hash Chain Audit Trail
- **Phase 11:** Modern OWL Command Center Dashboard & Visualizations
- **Phase 12:** Automated Test Suites & End-to-End Evaluation Workflow
- **Phase 13:** Final Verification, Demo Script, and Production Polish

---

## 11. Acceptance & Demonstration Criteria

The project is considered complete only when:
1. All core models and operations execute transactionally in PostgreSQL.
2. Invariant: $\text{Quant Stock} \equiv \sum \text{Ledger Movements}$ holds across all operations.
3. Outbox and Kafka publisher stream events seamlessly with partition keys.
4. Health engine generates transparent human-readable explanations.
5. What-if simulator projects outcomes with zero database mutations.
6. Audit trail validates hash integrity and detects injected tampering.
7. OWL Command Center displays live KPIs, heatmaps, and event timelines.
8. Comprehensive test suites achieve 100% pass rate.
9. All source code and documentation are committed and pushed to `origin/main`.
