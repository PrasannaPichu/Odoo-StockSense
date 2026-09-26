# -*- coding: utf-8 -*-
{
    'name': 'StockSense — Intelligent Inventory & Operational Decision Support',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Event-driven inventory management, Kafka streaming, explainable health engine, and command center',
    'description': """
StockSense: Intelligent, Event-Driven Inventory Management and Operational Decision Support System
=================================================================================================
"Don't just record inventory. Understand what is happening to inventory."

Key Capabilities:
-----------------
* Core Relational Source of Truth (PostgreSQL)
* Apache Kafka Event Streaming Backbone (Receipts, Deliveries, Transfers, Adjustments)
* Explainable Inventory Health Engine (Deterministic factor scoring with human-readable reasoning)
* Statistical & Deterministic Anomaly Detection Engine (Surge Z-Scores, repeated adjustments)
* Isolated In-Memory What-If Scenario Simulator (100% sandboxed, zero transactional mutation)
* Tamper-Evident SHA-256 Hash-Chained Audit Trail (Cryptographic block chain verification)
* Modern OWL Command Center Dashboard (Interactive SVG Warehouse Flow, Timeline, KPIs, Heatmaps)
    """,
    'author': 'StockSense Engineering Team',
    'website': 'https://github.com/PrasannaPichu/Odoo-StockSense',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/initial_data.xml',
        'views/menu_views.xml',
        'views/command_center_views.xml',
        'views/product_views.xml',
        'views/warehouse_views.xml',
        'views/location_views.xml',
        'views/quant_views.xml',
        'views/receipt_views.xml',
        'views/delivery_views.xml',
        'views/transfer_views.xml',
        'views/adjustment_views.xml',
        'views/stock_ledger_views.xml',
        'views/alert_views.xml',
        'views/audit_views.xml',
        'views/what_if_views.xml',
        'views/ocr_document_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stocksense/static/src/scss/stocksense.scss',
            'stocksense/static/src/components/command_center/command_center.xml',
            'stocksense/static/src/components/command_center/command_center.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
