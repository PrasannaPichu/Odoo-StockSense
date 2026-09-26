# -*- coding: utf-8 -*-
"""
StockSense Core Verification Test Suite
Comprehensive testing for inventory invariants, explainable health engine,
anomaly detection, simulator isolation, and tamper-evident audit hash chaining.
"""

import unittest
import copy
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from stocksense.services.audit_chain import GENESIS_HASH, compute_block_hash, verify_chain
from stocksense.services.health_engine import evaluate_product_health
from stocksense.services.anomaly_engine import detect_operational_anomalies
from stocksense.services.simulator_engine import simulate_hypothetical_scenario
from stocksense.services.kafka_producer import publish_event


class TestStockSenseCore(unittest.TestCase):

    def test_audit_chain_validity_and_tamper_detection(self):
        """Verify SHA-256 hash chaining and verify that tampering is detected."""
        blocks = []
        prev_hash = GENESIS_HASH

        # Generate 6 sequential blocks
        for seq in range(1, 7):
            payload = {
                'operation': 'RECEIPT_VALIDATED' if seq % 2 == 1 else 'DELIVERY_VALIDATED',
                'sku': 'STEEL-ROD-10MM',
                'quantity': float(seq * 25),
                'balance': float(100 + seq * 10)
            }
            curr_hash = compute_block_hash(payload, prev_hash)
            blocks.append({
                'sequence_number': seq,
                'previous_hash': prev_hash,
                'current_hash': curr_hash,
                'payload': payload
            })
            prev_hash = curr_hash

        # 1. Unaltered chain must verify with 100% success
        res = verify_chain(blocks)
        self.assertTrue(res['valid'], "Unaltered chain must be valid")
        self.assertEqual(res['total_verified'], 6)
        self.assertIsNone(res['broken_at_sequence'])

        # 2. Simulate malicious SQL tampering in Block #2
        tampered_blocks = copy.deepcopy(blocks)
        tampered_blocks[1]['payload']['quantity'] = 999.0  # Maliciously altered stock quantity!

        tampered_res = verify_chain(tampered_blocks)
        self.assertFalse(tampered_res['valid'], "Tampered chain must be detected as invalid")
        self.assertEqual(tampered_res['broken_at_sequence'], 2, "Tampering must break specifically at Block #2")
        self.assertIn("Hash mismatch at block 2", tampered_res['error_message'])

    def test_explainable_inventory_health_engine(self):
        """Verify deterministic scoring, status categories, and explainability factors."""
        # 1. Healthy State (Current: 120, Min: 50)
        healthy_eval = evaluate_product_health(
            current_stock=120.0,
            min_threshold=50.0,
            max_threshold=200.0,
            avg_daily_outflow=5.0
        )
        self.assertEqual(healthy_eval['health_status'], 'healthy')
        self.assertGreaterEqual(healthy_eval['health_score'], 75.0)
        self.assertTrue(len(healthy_eval['explanations']) > 0)
        self.assertEqual(healthy_eval['days_of_inventory'], 24.0)

        # 2. Attention State (Current: 42, Min: 50)
        attn_eval = evaluate_product_health(
            current_stock=42.0,
            min_threshold=50.0,
            avg_daily_outflow=8.0,
            pending_receipts_qty=0.0
        )
        self.assertEqual(attn_eval['health_status'], 'attention')
        self.assertLess(attn_eval['health_score'], 75.0)
        reasons = " ".join(attn_eval['explanations'])
        self.assertIn("below minimum threshold", reasons)
        self.assertIn("Zero pending supplier receipts", reasons)

        # 3. Critical State (Current: 0, Min: 50)
        crit_eval = evaluate_product_health(
            current_stock=0.0,
            min_threshold=50.0
        )
        self.assertEqual(crit_eval['health_status'], 'critical')
        self.assertLess(crit_eval['health_score'], 45.0)
        self.assertIn("OUT OF STOCK", crit_eval['explanations'][0])

        # 4. Overstock condition
        overstock_eval = evaluate_product_health(
            current_stock=250.0,
            min_threshold=50.0,
            max_threshold=200.0
        )
        self.assertTrue(any("Overstock Warning" in exp for exp in overstock_eval['explanations']))

    def test_anomaly_detection_rules_and_statistics(self):
        """Verify deterministic rules (deficit, repeated adjustments) and statistical Z-score surge."""
        # 1. Deterministic Rule: Deficit delivery attempt
        anomalies_deficit = detect_operational_anomalies(
            product_sku="BEARING-6204",
            current_operation_type="delivery",
            operation_quantity=75.0,
            available_stock=50.0
        )
        self.assertEqual(len(anomalies_deficit), 1)
        self.assertEqual(anomalies_deficit[0]['rule_code'], 'RULE_INSUFFICIENT_STOCK')
        self.assertEqual(anomalies_deficit[0]['severity'], 'critical')

        # 2. Deterministic Rule: Repeated manual adjustments (Shrinkage pattern)
        anomalies_adj = detect_operational_anomalies(
            product_sku="ALUM-SHEET-02",
            current_operation_type="adjustment",
            operation_quantity=3.0,
            available_stock=40.0,
            recent_adjustments_count_7d=4,
            total_adjusted_qty_7d=18.0
        )
        self.assertEqual(len(anomalies_adj), 1)
        self.assertEqual(anomalies_adj[0]['rule_code'], 'RULE_REPEATED_ADJUSTMENTS')

        # 3. Deterministic Rule: Dormant SKU Reactivation
        anomalies_dormant = detect_operational_anomalies(
            product_sku="IOT-SENSOR-V2",
            current_operation_type="delivery",
            operation_quantity=15.0,
            available_stock=30.0,
            days_since_last_movement=60
        )
        self.assertTrue(any(a['rule_code'] == 'RULE_DORMANT_STOCK_SURGE' for a in anomalies_dormant))

        # 4. Statistical Anomaly: Outbound consumption volume surge (Z-Score >= 3.0)
        baseline = [10.0, 12.0, 11.0, 9.0, 10.0, 11.0, 12.0, 10.0]
        anomalies_stat = detect_operational_anomalies(
            product_sku="STEEL-ROD-10MM",
            current_operation_type="delivery",
            operation_quantity=60.0,
            available_stock=100.0,
            historical_movements_qty=baseline
        )
        self.assertTrue(any(a['rule_code'] == 'STAT_OUTBOUND_SURGE_Z3' for a in anomalies_stat))

    def test_what_if_simulator_isolation_and_scenarios(self):
        """Verify simulator calculates hypothetical impacts without mutating input baseline state."""
        baseline_stock = 120.0
        min_thresh = 50.0

        # Scenario A: Delivery
        sim_deliv = simulate_hypothetical_scenario(
            current_stock=baseline_stock,
            min_threshold=min_thresh,
            max_threshold=200.0,
            scenario_type='delivery',
            quantity=80.0
        )
        self.assertEqual(sim_deliv['current_stock'], 120.0)
        self.assertEqual(baseline_stock, 120.0, "Input baseline stock must never be mutated!")
        self.assertEqual(sim_deliv['projected_stock'], 40.0)
        self.assertEqual(sim_deliv['stock_delta'], -80.0)
        self.assertEqual(sim_deliv['health_impact']['after']['health_status'], 'attention')

        # Scenario B: Receipt
        sim_rec = simulate_hypothetical_scenario(
            current_stock=40.0,
            min_threshold=min_thresh,
            max_threshold=200.0,
            scenario_type='receipt',
            quantity=60.0
        )
        self.assertEqual(sim_rec['projected_stock'], 100.0)
        self.assertEqual(sim_rec['stock_delta'], 60.0)
        self.assertEqual(sim_rec['health_impact']['after']['health_status'], 'healthy')

        # Scenario C: Internal Transfer Invariant
        sim_trf = simulate_hypothetical_scenario(
            current_stock=100.0,
            min_threshold=min_thresh,
            max_threshold=200.0,
            scenario_type='transfer',
            quantity=30.0,
            source_location_stock=50.0,
            dest_location_stock=20.0
        )
        self.assertEqual(sim_trf['stock_delta'], 0.0, "Total company inventory delta must be 0 for transfers")
        self.assertEqual(sim_trf['projected_stock'], 100.0)

    def test_kafka_producer_resilience(self):
        """Verify Kafka producer handles missing broker gracefully with structured envelope."""
        result = publish_event(
            topic="stocksense.inventory.events",
            event_type="TEST_EVENT",
            payload={"product_id": 1, "test": True},
            partition_key="1"
        )
        self.assertIn('event_id', result)
        self.assertTrue(result['event_id'].startswith('evt_'))
        self.assertEqual(result['topic'], 'stocksense.inventory.events')


if __name__ == '__main__':
    unittest.main()
