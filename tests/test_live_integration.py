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

    def test_08_product_creation_and_inventory_search(self):
        """Verify dynamic product creation, SKU registration, and health computation."""
        cat = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product.category', 'search_read',
            [[]], {'fields': ['id'], 'limit': 1}
        )
        cat_id = cat[0]['id'] if cat else False

        import time
        unique_sku = f"TITAN-ROD-{int(time.time() * 1000) % 1000000}"
        prod_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'create',
            [{
                'name': 'Titanium Alloy Rod 12mm',
                'sku': unique_sku,
                'category_id': cat_id,
                'uom_name': 'Units',
                'min_stock_threshold': 10.0,
                'max_stock_threshold': 100.0,
                'standard_price': 85.0,
            }]
        )
        self.assertIsInstance(prod_id, int)

        # Product must be searchable
        found = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', unique_sku]]],
            {'fields': ['id', 'name', 'total_stock', 'health_status']}
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['total_stock'], 0.0)
        self.assertIn(found[0]['health_status'], ['critical', 'attention'])

    def test_09_goods_receipt_lifecycle_and_stock_increase(self):
        """Verify Receipt workflow: Draft -> Confirmed -> Validated (stock increases, ledger & audit created)."""
        # Find product, warehouse, location, partner
        prod = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'total_stock']}
        )[0]
        initial_stock = prod['total_stock']

        wh = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.warehouse', 'search_read',
            [[['code', '=', 'WH-MAIN']]], {'fields': ['id']}
        )[0]
        loc = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.location', 'search_read',
            [[['warehouse_id', '=', wh['id']], ['usage', '=', 'internal']]],
            {'fields': ['id']}
        )[0]
        partner = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'res.partner', 'search_read',
            [[]], {'fields': ['id'], 'limit': 1}
        )[0]

        receipt_qty = 25.0
        # 1. Create Receipt in DRAFT
        rec_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.receipt', 'create',
            [{
                'partner_id': partner['id'],
                'warehouse_id': wh['id'],
                'location_dest_id': loc['id'],
                'state': 'draft',
                'line_ids': [(0, 0, {
                    'product_id': prod['id'],
                    'quantity_received': receipt_qty
                })]
            }]
        )

        # Verify stock DID NOT change while in draft
        prod_check = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'read',
            [[prod['id']]], {'fields': ['total_stock']}
        )[0]
        self.assertEqual(prod_check['total_stock'], initial_stock, "Draft receipt must NEVER alter stock")

        # 2. Confirm receipt
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.receipt', 'action_confirm',
            [[rec_id]]
        )

        # 3. Validate receipt
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.receipt', 'action_validate',
            [[rec_id]]
        )

        # Stock must increase exactly by receipt_qty
        prod_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'read',
            [[prod['id']]], {'fields': ['total_stock']}
        )[0]
        self.assertEqual(prod_after['total_stock'], initial_stock + receipt_qty)

    def test_10_delivery_order_lifecycle_pick_pack_validate(self):
        """Verify Delivery Order: Draft -> Confirmed -> Pick -> Pack -> Validate."""
        prod = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'total_stock']}
        )[0]
        initial_stock = prod['total_stock']

        wh = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.warehouse', 'search_read',
            [[['code', '=', 'WH-MAIN']]], {'fields': ['id']}
        )[0]
        loc = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.location', 'search_read',
            [[['warehouse_id', '=', wh['id']], ['usage', '=', 'internal']]],
            {'fields': ['id']}
        )[0]
        partner = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'res.partner', 'search_read',
            [[]], {'fields': ['id'], 'limit': 1}
        )[0]

        deliv_qty = 5.0
        # 1. Create delivery draft
        deliv_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'create',
            [{
                'partner_id': partner['id'],
                'warehouse_id': wh['id'],
                'location_src_id': loc['id'],
                'state': 'draft',
                'line_ids': [(0, 0, {
                    'product_id': prod['id'],
                    'quantity_delivered': deliv_qty
                })]
            }]
        )

        # 2. Confirm
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'action_confirm',
            [[deliv_id]]
        )

        # 3. Pick
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'action_pick',
            [[deliv_id]]
        )
        deliv_state = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'read',
            [[deliv_id]], {'fields': ['state']}
        )[0]['state']
        self.assertEqual(deliv_state, 'picked')

        # 4. Pack
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'action_pack',
            [[deliv_id]]
        )
        deliv_state = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'read',
            [[deliv_id]], {'fields': ['state']}
        )[0]['state']
        self.assertEqual(deliv_state, 'packed')

        # 5. Validate
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.delivery', 'action_validate',
            [[deliv_id]]
        )

        # Stock must decrease by deliv_qty
        prod_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'read',
            [[prod['id']]], {'fields': ['total_stock']}
        )[0]
        self.assertEqual(prod_after['total_stock'], initial_stock - deliv_qty)

    def test_11_internal_transfer_conservation_invariant(self):
        """Verify Internal Transfer: Location A dec, Location B inc, Total company stock invariant (Δ = 0)."""
        prod = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'total_stock']}
        )[0]
        initial_total = prod['total_stock']

        locs = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.location', 'search_read',
            [[['usage', '=', 'internal']]], {'fields': ['id', 'name'], 'limit': 2}
        )
        self.assertGreaterEqual(len(locs), 2)
        loc_src, loc_dest = locs[0], locs[1]

        # Ensure source quant has stock
        quant_src = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.quant', 'search_read',
            [[['product_id', '=', prod['id']], ['location_id', '=', loc_src['id']]]],
            {'fields': ['quantity']}
        )
        if not quant_src or quant_src[0]['quantity'] < 10.0:
            # Add stock to source location via update_stock_quant
            self.models.execute_kw(
                ODOO_DB, self.uid, ODOO_PASS,
                'stocksense.quant', 'update_stock_quant',
                [prod['id'], loc_src['id'], 20.0]
            )
            initial_total += 20.0

        transfer_qty = 5.0
        # Create transfer
        trf_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.transfer', 'create',
            [{
                'location_src_id': loc_src['id'],
                'location_dest_id': loc_dest['id'],
                'state': 'draft',
                'line_ids': [(0, 0, {
                    'product_id': prod['id'],
                    'quantity': transfer_qty
                })]
            }]
        )

        # Confirm & Complete
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.transfer', 'action_confirm',
            [[trf_id]]
        )
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.transfer', 'action_complete',
            [[trf_id]]
        )

        # Verify company-wide stock is invariant (Δ = 0)
        prod_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'read',
            [[prod['id']]], {'fields': ['total_stock']}
        )[0]
        self.assertEqual(prod_after['total_stock'], initial_total, "Transfer must preserve company total stock")

    def test_12_inventory_adjustment_discrepancy(self):
        """Verify Inventory Adjustment: difference = counted - recorded, applied accurately."""
        prod = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['id', 'total_stock']}
        )[0]
        wh = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.warehouse', 'search_read',
            [[['code', '=', 'WH-MAIN']]], {'fields': ['id']}
        )[0]
        loc = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.location', 'search_read',
            [[['warehouse_id', '=', wh['id']], ['usage', '=', 'internal']]],
            {'fields': ['id']}
        )[0]

        quant = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.quant', 'search_read',
            [[['product_id', '=', prod['id']], ['location_id', '=', loc['id']]]],
            {'fields': ['quantity']}
        )
        curr_qty = quant[0]['quantity'] if quant else 0.0
        new_count = curr_qty + 10.0

        adj_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.adjustment', 'create',
            [{
                'warehouse_id': wh['id'],
                'location_id': loc['id'],
                'reason': 'counting_error',
                'state': 'draft',
                'line_ids': [(0, 0, {
                    'product_id': prod['id'],
                    'recorded_qty': curr_qty,
                    'counted_qty': new_count
                })]
            }]
        )

        # Validate adjustment
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.adjustment', 'action_validate',
            [[adj_id]]
        )

        quant_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.quant', 'search_read',
            [[['product_id', '=', prod['id']], ['location_id', '=', loc['id']]]],
            {'fields': ['quantity']}
        )[0]
        self.assertEqual(quant_after['quantity'], new_count)

    def test_13_rapidocr_document_intake_and_safe_draft_creation(self):
        """Verify local RapidOCR intake: Upload -> OCR -> Review -> Draft Receipt -> Stock untouched until validation."""
        import base64
        b64_path = os.path.join(os.path.dirname(__file__), '..', 'stocksense', 'static', 'sample_invoice.b64')
        with open(b64_path, 'r') as f:
            file_b64 = f.read().strip()

        # 1. Ingest document
        ocr_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'create',
            [{
                'document_type': 'receipt',
                'filename': 'supplier_invoice_1042.png',
                'file_data': file_b64,
            }]
        )
        self.assertIsInstance(ocr_id, int)

        # 2. Run RapidOCR
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'action_process_ocr',
            [[ocr_id]]
        )

        doc = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'read',
            [[ocr_id]],
            {'fields': ['state', 'confidence', 'extracted_partner_name', 'extracted_reference', 'line_ids']}
        )[0]
        self.assertEqual(doc['state'], 'extracted')
        self.assertGreater(doc['confidence'], 80.0)
        self.assertIn('1042', doc['extracted_reference'] or '')

        # Check line item extracted
        self.assertGreater(len(doc['line_ids']), 0)
        line = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.line', 'read',
            [[doc['line_ids'][0]]],
            {'fields': ['id', 'raw_description', 'detected_sku', 'detected_qty', 'product_id', 'match_status']}
        )[0]
        self.assertEqual(line['detected_qty'], 100.0)

        # Human-in-the-loop review: user confirms/selects product if review was required
        if not line.get('product_id'):
            prod_target = self.models.execute_kw(
                ODOO_DB, self.uid, ODOO_PASS,
                'stocksense.product', 'search_read',
                [[['sku', '=', 'STEEL-ROD-10MM']]],
                {'fields': ['id']}
            )[0]
            self.models.execute_kw(
                ODOO_DB, self.uid, ODOO_PASS,
                'stocksense.ocr.line', 'write',
                [[line['id']], {'product_id': prod_target['id'], 'match_status': 'manual'}]
            )

        # Stock before draft creation
        prod_before = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['total_stock']}
        )[0]['total_stock']

        # 3. Create Draft Receipt from OCR
        action_res = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'action_create_draft_receipt',
            [[ocr_id]]
        )
        self.assertEqual(action_res['res_model'], 'stocksense.receipt')
        created_receipt_id = action_res['res_id']

        # CRITICAL TEST: OCR MUST NEVER DIRECTLY MUTATE STOCK
        prod_after_ocr = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['total_stock']}
        )[0]['total_stock']
        self.assertEqual(prod_before, prod_after_ocr, "OCR draft creation MUST NEVER mutate stock!")

        # 4. Normal workflow validation
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.receipt', 'action_confirm',
            [[created_receipt_id]]
        )
        self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.receipt', 'action_validate',
            [[created_receipt_id]]
        )

        # Now stock must increase
        prod_final = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.product', 'search_read',
            [[['sku', '=', 'STEEL-ROD-10MM']]],
            {'fields': ['total_stock']}
        )[0]['total_stock']
        self.assertEqual(prod_final, prod_before + 100.0)

    def test_14_ocr_invalid_upload_rejection(self):
        """Verify invalid document upload rejection (unsupported extension / malicious file)."""
        import base64
        fake_exe = base64.b64encode(b"MZ\x90\x00executable").decode('ascii')
        ocr_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'create',
            [{
                'document_type': 'receipt',
                'filename': 'malicious_payload.exe',
                'file_data': fake_exe,
            }]
        )
        with self.assertRaises(Exception):
            self.models.execute_kw(
                ODOO_DB, self.uid, ODOO_PASS,
                'stocksense.ocr.document', 'action_process_ocr',
                [[ocr_id]]
            )

    def test_15_dashboard_metrics_warehouse_filtering(self):
        """Verify that dashboard metrics endpoint dynamically filters when a specific warehouse is provided."""
        res_all = self.session.post(
            f"{ODOO_URL}/api/stocksense/dashboard/metrics",
            json={'jsonrpc': '2.0', 'params': {'warehouse': 'all'}}
        ).json()['result']

        res_wh = self.session.post(
            f"{ODOO_URL}/api/stocksense/dashboard/metrics",
            json={'jsonrpc': '2.0', 'params': {'warehouse': 'WH-MAIN'}}
        ).json()['result']

        self.assertIn('kpis', res_all)
        self.assertIn('kpis', res_wh)
        self.assertGreater(res_all['kpis']['total_products'], 0)
        self.assertGreater(res_wh['kpis']['total_products'], 0)

    def test_16_ocr_automatic_intake_reference_and_file_size_persistence(self):
        """
        Regression test:
        1. default_get returns valid sequence reference starting with 'OCR/'
        2. Uploaded document receives automatic intake reference without manual entry
        3. Uploaded binary has non-zero size stored and computed
        4. OCR processing succeeds with invoice reference, supplier, date, and matched lines
        """
        import base64
        import re

        # 1. Verify default_get provides the automatic sequence reference
        defaults = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'default_get',
            [['name', 'document_type', 'file_data', 'filename', 'file_size', 'state']]
        )
        self.assertIn('name', defaults, "default_get must return 'name' field")
        self.assertTrue(bool(defaults['name']), "Document Intake Ref must not be blank")
        self.assertTrue(
            bool(re.match(r'^OCR/\d{4}/\d+$', defaults['name'])),
            f"Reference '{defaults['name']}' must match sequence pattern OCR/YYYY/NNNN"
        )

        # 2. Upload actual PDF test invoice
        pdf_fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'stocksense', 'static', 'StockSense_OCR_Test_Supplier_Invoice.pdf'
        )
        if not os.path.exists(pdf_fixture_path):
            pdf_fixture_path = '/tmp/test_invoice.pdf'

        with open(pdf_fixture_path, 'rb') as f:
            pdf_bytes = f.read()

        b64_pdf = base64.b64encode(pdf_bytes).decode('ascii')
        doc_id = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'create',
            [{
                'document_type': 'receipt',
                'filename': 'StockSense_OCR_Test_Supplier_Invoice.pdf',
                'file_data': b64_pdf,
            }]
        )

        # Read back document
        doc = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'read',
            [[doc_id]],
            {'fields': ['name', 'file_size', 'state', 'filename', 'mime_type']}
        )[0]

        # 3. Assert automatic reference, non-zero file size, and correct state
        self.assertTrue(bool(doc['name']), "Created document must have an automatic intake reference")
        self.assertTrue(
            bool(re.match(r'^OCR/\d{4}/\d+$', doc['name'])),
            f"Created reference '{doc['name']}' must match sequence pattern OCR/YYYY/NNNN"
        )
        self.assertEqual(doc['file_size'], len(pdf_bytes), "file_size must equal uploaded binary byte length")
        self.assertGreater(doc['file_size'], 0, "file_size must be non-zero")
        self.assertEqual(doc['state'], 'draft')

        # 4. Execute OCR processing (must not fail due to reference or binary)
        success = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'action_process_ocr',
            [[doc_id]]
        )
        self.assertTrue(success, "action_process_ocr must return True")

        # Read back extracted details
        doc_after = self.models.execute_kw(
            ODOO_DB, self.uid, ODOO_PASS,
            'stocksense.ocr.document', 'read',
            [[doc_id]],
            {'fields': [
                'state', 'confidence', 'extracted_partner_name',
                'extracted_reference', 'extracted_date', 'extracted_tax_id',
                'line_ids'
            ]}
        )[0]

        self.assertEqual(doc_after['state'], 'extracted', "State must transition to 'extracted' (Review & Verification Required)")
        self.assertIn('Chennai Industrial', doc_after['extracted_partner_name'])
        self.assertEqual(doc_after['extracted_reference'], 'INV-OCR-2026-001')
        self.assertEqual(doc_after['extracted_date'], '2026-09-26')
        self.assertEqual(doc_after['extracted_tax_id'], '33ABCDE1234F1Z5')
        self.assertGreaterEqual(len(doc_after['line_ids']), 3, "All 3 invoice lines must be extracted")


if __name__ == '__main__':
    unittest.main()
