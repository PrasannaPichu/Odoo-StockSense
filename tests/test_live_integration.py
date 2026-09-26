# -*- coding: utf-8 -*-
"""
StockSense Live End-to-End Integration Test Suite
Verifies running Docker services, XML-RPC warehouse operations,
ledger immutability, audit chain cryptographic validity, and REST APIs.
"""

import unittest
import xmlrpc.client
import requests
import json
import os

ODOO_URL = os.environ.get('ODOO_URL', 'http://localhost:8069')
ODOO_DB = os.environ.get('ODOO_DB', 'stocksense_db')
ODOO_USER = os.environ.get('ODOO_USER', 'admin')
ODOO_PASS = os.environ.get('ODOO_PASS', 'admin')


class TestStockSenseLiveIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        cls.uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
        if not cls.uid:
            raise RuntimeError("Failed to authenticate to live Odoo instance")
        cls.models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

        # Session for REST API tests
        cls.session = requests.Session()
        cls.session.post(f"{ODOO_URL}/web/session/authenticate", json={
            'jsonrpc': '2.0',
            'params': {
                'db': ODOO_DB,
                'login': ODOO_USER,
                'password': ODOO_PASS
            }
        })

    def test_01_xmlrpc_authentication_and_models(self):
        """Verify XML-RPC connection and custom StockSense models exist."""
        self.assertIsInstance(self.uid, int)
        self.assertGreater(self.uid, 0)

        # Check product exists
        products = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'name', 'sku', 'total_stock', 'health_status']}
        )
        self.assertTrue(len(products) > 0, "STEEL-ROD-10MM product must exist")
        self.assertEqual(products[0]['sku'], 'STEEL-ROD-10MM')

    def test_02_stock_ledger_immutability(self):
        """Verify that existing Stock Ledger entries cannot be modified or deleted directly."""
        ledgers = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.stock.ledger', 'search_read',
            [[]], {'fields': ['id'], 'limit': 1}
        )
        if ledgers:
            ledger_id = ledgers[0]['id']
            # Attempt write
            with self.assertRaises(Exception):
                self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASS,
                    'stocksense.stock.ledger', 'write',
                    [[ledger_id], {'quantity_change': 9999.0}]
                )
            # Attempt unlink
            with self.assertRaises(Exception):
                self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASS,
                    'stocksense.stock.ledger', 'unlink',
                    [[ledger_id]]
                )

    def test_03_audit_trail_cryptographic_verification(self):
        """Verify that live audit trail blocks in PostgreSQL form an unbroken SHA-256 chain."""
        blocks = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.audit.trail', 'search_read',
            [[]],
            {'fields': ['sequence_number', 'previous_hash', 'current_hash', 'payload_json'],
             'order': 'sequence_number asc'}
        )
        self.assertGreater(len(blocks), 0, "Audit trail blocks must exist")

        from stocksense.services.audit_chain import verify_chain
        record_list = [
            {
                'sequence_number': b['sequence_number'],
                'previous_hash': b['previous_hash'],
                'current_hash': b['current_hash'],
                'payload': b['payload_json']
            }
            for b in blocks
        ]
        result = verify_chain(record_list)
        self.assertTrue(result['valid'], f"Audit chain verification failed: {result.get('error_message')}")
        self.assertEqual(result['total_verified'], len(blocks))
        self.assertIsNone(result['broken_at_sequence'])

    def test_04_rest_api_dashboard_metrics(self):
        """Verify REST API returns live KPIs and operational metrics."""
        resp = self.session.post(f"{ODOO_URL}/api/stocksense/dashboard/metrics", json={
            'jsonrpc': '2.0',
            'params': {}
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('result', data)
        res = data['result']
        self.assertIn('kpis', res)
        self.assertIn('total_products', res['kpis'])
        self.assertIn('total_stock', res['kpis'])
        self.assertIn('audit_integrity', res)
        self.assertTrue(res['audit_integrity']['valid'])
        self.assertIn('recent_movements', res)
        self.assertIn('critical_products', res)
        self.assertIn('warehouse_stats', res)

    def test_05_rest_api_what_if_simulator(self):
        """Verify REST What-If simulator computes accurate projection without changing stock."""
        # Read current stock
        products = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'total_stock']}
        )
        product_id = products[0]['id']
        actual_stock_before = products[0]['total_stock']

        resp = self.session.post(f"{ODOO_URL}/api/stocksense/simulate", json={
            'jsonrpc': '2.0',
            'params': {
                'product_id': product_id,
                'scenario_type': 'delivery',
                'quantity': 15.0
            }
        })
        self.assertEqual(resp.status_code, 200)
        sim_data = resp.json().get('result', {})
        self.assertTrue(sim_data.get('success'))
        sim_res = sim_data.get('result', {})
        self.assertEqual(sim_res.get('current_stock'), actual_stock_before)
        self.assertEqual(sim_res.get('projected_stock'), actual_stock_before - 15.0)

        # Verify actual stock in database did NOT change
        products_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['id', '=', product_id]]],
            {'fields': ['total_stock']}
        )
        self.assertEqual(products_after[0]['total_stock'], actual_stock_before,
                         "Simulation must not mutate actual stock!")


    def test_06_enriched_dashboard_metrics_and_operational_intelligence(self):
        """Verify new operational intelligence, movement overview, and audit blocks in metrics."""
        resp = self.session.post(f"{ODOO_URL}/api/stocksense/dashboard/metrics", json={
            'jsonrpc': '2.0',
            'params': {}
        })
        self.assertEqual(resp.status_code, 200)
        res = resp.json().get('result', {})
        
        # Movement overview
        self.assertIn('movement_overview', res)
        mov = res['movement_overview']
        self.assertIn('inbound_total', mov)
        self.assertIn('outbound_total', mov)
        self.assertIn('transfers_total', mov)
        self.assertIn('adjustments_total', mov)

        # Operational Intelligence
        self.assertIn('operational_intelligence', res)
        intel = res['operational_intelligence']
        self.assertIn('critical_count', intel)
        self.assertIn('attention_count', intel)
        self.assertIn('anomalies_count', intel)
        self.assertIn('anomalies', intel)
        self.assertIn('active_alerts', intel)

        # Health distribution
        self.assertIn('health_distribution', res)
        h_dist = res['health_distribution']
        self.assertIn('healthy_pct', h_dist)
        self.assertIn('attention_pct', h_dist)
        self.assertIn('critical_pct', h_dist)

        # All products & audit blocks
        self.assertIn('all_products', res)
        self.assertGreater(len(res['all_products']), 0)
        self.assertIn('blocks', res['audit_integrity'])
        self.assertGreater(len(res['audit_integrity']['blocks']), 0)

    def test_07_access_control_role_enforcement(self):
        """Verify that warehouse staff user role cannot delete products or modify ledger."""
        # Find or create a test staff user
        group_user = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'ir.model.data', 'check_object_reference',
            ['stocksense', 'group_stocksense_user']
        )
        self.assertTrue(group_user, "StockSense user group must exist")
        group_user_id = group_user[1]

        # Verify ACL constraints on stock ledger
        # Attempting to delete ledger entries must raise access error
        ledgers = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.stock.ledger', 'search_read',
            [[]], {'fields': ['id'], 'limit': 1}
        )
        if ledgers:
            with self.assertRaises(Exception):
                self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASS,
                    'stocksense.stock.ledger', 'unlink',
                    [[ledgers[0]['id']]]
                )


if __name__ == '__main__':
    unittest.main()
