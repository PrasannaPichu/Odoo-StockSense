# StockSense — Intelligent, Event-Driven Inventory Management and Operational Decision Support System

[![Odoo Version](https://img.shields.io/badge/Odoo-17.0-purple.svg)](https://www.odoo.com)
[![Python Version](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%7C%2017-336791.svg)](https://www.postgresql.org)
[![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-3.7.0-red.svg)](https://kafka.apache.org)
[![Tests](https://img.shields.io/badge/Tests-100%25%20Passing-success.svg)](https://github.com/PrasannaPichu/Odoo-StockSense)
[![Audit Integrity](https://img.shields.io/badge/Audit-SHA--256%20Hash%20Chained-emerald.svg)](https://github.com/PrasannaPichu/Odoo-StockSense)
[![License](https://img.shields.io/badge/License-LGPL--3-blue.svg)](LICENSE)

> **Hackathon:** Odoo x GCET Hyderabad Hackathon 2026  
> **Core Motto:** *"Don't just record inventory. Understand what is happening to inventory."*

---

## 1. Executive Overview

Traditional ERP inventory modules behave as passive digital ledgers. They faithfully record receipts and deliveries, but fail to interpret the operational pulse of the warehouse. Discrepancies emerge days or weeks later during manual inventory counts, stock-outs trigger panic re-orders, and supervisors lack forward-looking visibility into how operational shifts cascade through downstream logistics.

**StockSense** transforms the Odoo inventory experience into an **active, event-driven operational decision-support system**. Built natively on Odoo 17 (Python, OWL, PostgreSQL), backed by an asynchronous **Apache Kafka** event streaming cluster, and powered by an **Explainable Inventory Health Engine**, StockSense guarantees:
1. **Absolute Transactional Determinism:** PostgreSQL serves as the ACID single source of truth for stock quantities and immutable double-entry ledgers.
2. **Real-Time Asynchronous Decoupling:** Every warehouse operation (Receipts, Deliveries, Transfers, Adjustments) emits structured events to Kafka partitioned by `product_id`.
3. **Continuous Intelligence & Explainability:** Dedicated consumer micro-services analyze telemetry to evaluate health scores, detect operational anomalies (e.g. erratic adjustments, phantom depletion, velocity spikes), and generate human-readable causal explanations—not black-box numbers.
4. **Predictive Scenario Simulation:** An isolated "What-If" simulator enables warehouse supervisors to test hypotheticals (e.g. bulk orders, supplier delays) without mutating transactional state.
5. **Tamper-Evident Forensic Audit:** A cryptographic SHA-256 hash-chained ledger ensures that every inventory transition is forensically verifiable and immutable.
6. **Executive Command Center:** A modern, multi-palette, responsive OWL frontend featuring live KPI cards, interactive warehouse flow diagrams, chronological stock timelines, and multi-dimensional filtering.

---

## 2. System Architecture

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

---

## 3. Technology Stack

| Layer | Component | Description |
|---|---|---|
| **Core Framework** | Odoo 17.0 / Python 3.12 | Core ORM, Business Logic, Security Groups, Actions, XML Views |
| **Database** | PostgreSQL 16/17 | ACID Source of Truth, Row-Level Locking, Unique Constraints |
| **Event Streaming** | Apache Kafka 3.7.0 (KRaft) | Topic Partitioning, At-Least-Once Delivery, Consumer Groups |
| **Frontend / UI** | JavaScript (ES6+), OWL 2, SCSS | Reactive Command Center, SVG Flow Map, Interactive Timeline |
| **Analytics Engine** | Pandas, NumPy, SciPy | Rolling Window Consumption, Z-Score Outbound Surge Detection |
| **Security & Audit** | Python `hashlib` (SHA-256) | Tamper-Evident Hash Chain, Odoo Access Controls (ACLs) |
| **Test Suite** | Python `unittest`, `pytest` | Business Rule Verification, Invariant Checks, Anomaly Tests |

---

## 4. Key Differentiating Capabilities

### 4.1 Explainable Inventory Health Engine
Instead of showing an arbitrary black-box risk score, StockSense evaluates four explicit operational pillars:
- **Stock Ratio Factor (40%):** $\frac{\text{Current Stock}}{\text{Min Safety Threshold}}$
- **Consumption Velocity Factor (30%):** Days of Inventory Remaining based on 14-day trailing consumption.
- **Inbound Replenishment Coverage (20%):** Scheduled confirmed supplier receipts due before depletion.
- **Physical Stability & Shrinkage (10%):** Penalizes repeated manual adjustments and damage write-offs.

Every evaluation outputs categorical states (`HEALTHY`, `ATTENTION`, `CRITICAL`) paired with **plain-English diagnostic bullet points**:
* *"Current stock (42 units) is 8 units below minimum threshold (50)."*
* *"Outbound velocity has surged by 45% over the 14-day baseline."*
* *"Zero pending supplier receipts scheduled to replenish deficit!"*

### 4.2 Deterministic & Statistical Anomaly Detection
- **Deficit Delivery Blocker:** Catches attempts to fulfill beyond available physical quant stock.
- **Repeated Adjustments Anomaly:** Flags SKUs adjusted $\ge 3$ times within a rolling 7-day window (theft, shrinkage, or counting errors).
- **Z-Score Velocity Surge:** Identifies sudden demand surges where movement quantity deviates by $Z \ge 3.0$ from normal consumption baseline:
  $$Z = \frac{Q - \mu}{\sigma}$$
- **Dormant SKU Reactivation:** Flags sudden massive withdrawals on SKUs with zero movements for $> 45$ days.

### 4.3 Sandboxed In-Memory What-If Simulator
Warehouse managers can evaluate hypothetical scenarios without risking transactional corruption:
- **Zero Database Mutation:** Runs entirely in Python memory against cloned state snapshots.
- **Multi-Scenario Testing:** Simulates bulk customer dispatches, expedited receipts, or multi-location rebalances.
- **Predictive Guidance:** Outputs projected stock, health state shift (`HEALTHY` $\rightarrow$ `CRITICAL`), and required safety re-order quantities.

### 4.4 Tamper-Evident SHA-256 Hash-Chained Audit Trail
Forensic auditability built into every inventory transaction:
- **Genesis Block:** Initialized with $\text{SHA256}(\text{"STOCKSENSE\_GENESIS\_2026"})$.
- **Continuous Chaining:** Block $N$ hash = $\text{SHA256}(\text{Canonical Payload}_N + \text{Previous Hash}_{N-1})$.
- **Tamper Detection:** If any historical database row is modified via raw SQL, the verification routine immediately detects a signature mismatch and identifies the exact compromised block.

---

## 5. Event Streaming Architecture (Kafka)

### Topic Governance

| Topic Name | Partition Key | Retention | Purpose |
|---|---|---|---|
| `stocksense.inventory.events` | `product_id` (String) | 7 days | Operational ledger events (Receipts, Deliveries, Transfers, Adjustments) |
| `stocksense.inventory.alerts` | `product_id` (String) | 30 days | Real-time threshold breaches and anomaly escalations |
| `stocksense.inventory.analytics` | `warehouse_id` (String) | 7 days | Aggregated turnover metrics and velocity baselines |
| `stocksense.inventory.audit` | `sequence_number` (String) | Permanent | Cryptographic hash-chain block confirmations |

### Resilient Outbox Fallback
If Kafka brokers become temporarily unreachable during network partition:
- Odoo database transactions **succeed without interruption**.
- Events are queued into PostgreSQL table `stocksense.event.outbox` with status `pending`.
- A background worker flushes queued events upon broker reconnection, ensuring **at-least-once delivery** and **zero data loss**.

---

## 6. Quickstart & Installation

### Option A: Complete Docker Compose Stack (Recommended)

1. **Clone Repository:**
   ```bash
   git clone https://github.com/PrasannaPichu/Odoo-StockSense.git
   cd Odoo-StockSense
   ```

2. **Boot All Services:**
   ```bash
   docker compose up -d
   ```
   *This starts PostgreSQL 16 (port 5433), Apache Kafka (port 9092), Odoo 17 (port 8069), and the independent Consumer workers.*

3. **Access StockSense Command Center:**
   - URL: `http://localhost:8069`
   - Database: `stocksense_db`
   - Master / Admin Login: `admin` / `admin`

---

## 7. Running Automated Test Suites

StockSense includes an end-to-end automated test suite verifying invariants, anomaly rules, simulator isolation, and cryptographic audit hashing:

```bash
# Activate virtual environment
source .venv/bin/activate

# Execute PyTest suite
pytest -v tests/test_stocksense_core.py
```

### Test Suite Output:
```
tests/test_stocksense_core.py::TestStockSenseCore::test_anomaly_detection_rules_and_statistics PASSED
tests/test_stocksense_core.py::TestStockSenseCore::test_audit_chain_validity_and_tamper_detection PASSED
tests/test_stocksense_core.py::TestStockSenseCore::test_explainable_inventory_health_engine PASSED
tests/test_stocksense_core.py::TestStockSenseCore::test_kafka_producer_resilience PASSED
tests/test_stocksense_core.py::TestStockSenseCore::test_what_if_simulator_isolation_and_scenarios PASSED

============================== 5 passed in 0.14s ===============================
```

---

## 8. Master Demonstration Walkthrough (Evaluator Script)

To execute the complete 8-step evaluation demonstration automatically:

```bash
python scripts/seed_demo_data.py
```

### Step-by-Step Evaluator Narrative:
1. **Login & Dashboard:** Open `http://localhost:8069`, access the **StockSense Command Center** to view live KPIs, multi-warehouse distribution, and verified audit status.
2. **Goods Receipt:** Receive 100 units of *High-Tensile Steel Rod 10mm* into Main Warehouse Rack A. Observe quant increment and immutable ledger creation.
3. **Kafka Event Streaming:** Verify event `RECEIPT_VALIDATED` is published to Kafka and consumed by Analytics and Audit workers.
4. **Internal Transfer:** Relocate 40 units from *Rack A* to *Production Floor*. Observe location quants update while total company inventory remains strictly invariant ($\Delta = 0$).
5. **Customer Delivery:** Fulfill customer order of 20 units. Verify stock decrement to 80 units and double-entry ledger entry.
6. **Physical Adjustment:** Log cycle count audit with 5 damaged units. Mandatory reason code (`damage`) recorded; ledger and audit block updated.
7. **Low-Stock Alert & Explanation:** Dispatch 35 units to drop inventory below safety minimum. Observe the **Health Engine** shift status to `ATTENTION` / `CRITICAL` with bulleted causal reasons.
8. **What-If Simulation:** Test a hypothetical 30-unit order in the simulator. Verify projected stock-out warning and decision-support guidance with **zero database mutation**.
9. **Forensic Audit Integrity:** Click **Verify Forensic Chain Integrity** in the Audit Trail view to prove 100% cryptographic SHA-256 validity across all operations.

---

## 9. Security & Access Control

- **Warehouse Staff (`group_stocksense_user`):** Operational processing (Receipts, Deliveries, Transfers, Adjustments).
- **Inventory Manager (`group_stocksense_manager`):** Full configuration, forensic audit verification, outbox management, and threshold tuning.
- **Backend Validation:** All permissions and business rules enforced at the Odoo ORM level—never solely relying on UI hiding.

---

## 10. Repository & Development Journey

StockSense adheres strictly to the single-branch Git workflow (`main`):
- Master PRD Specification (`PRD.md`) committed and pushed first.
- Incremental, verified feature commits across models, services, views, OWL frontend, and Kafka streaming.
- Rigorous test-driven verification before every commit.

*Built with passion for the Odoo x GCET Hyderabad Hackathon 2026.*
