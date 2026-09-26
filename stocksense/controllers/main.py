# -*- coding: utf-8 -*-
import json
import logging
from odoo import http, _
from odoo.http import request
from ..services.audit_chain import verify_chain
from ..services.simulator_engine import simulate_hypothetical_scenario

_logger = logging.getLogger(__name__)

class StocksenseDashboardController(http.Controller):

    @http.route('/api/stocksense/dashboard/metrics', type='json', auth='user', methods=['POST', 'GET'])
    def get_dashboard_metrics(self, **kwargs):
        """Returns consolidated live metrics for the Command Center."""
        products = request.env['stocksense.product'].search([])
        total_products = len(products)
        total_stock = sum(products.mapped('total_stock'))
        total_valuation = sum(products.mapped('stock_valuation'))

        healthy_count = len(products.filtered(lambda p: p.health_status == 'healthy'))
        attention_count = len(products.filtered(lambda p: p.health_status == 'attention'))
        critical_count = len(products.filtered(lambda p: p.health_status == 'critical'))

        open_alerts = request.env['stocksense.inventory.alert'].search([('state', '=', 'new')])
        pending_receipts = request.env['stocksense.receipt'].search_count([('state', 'in', ['draft', 'confirmed'])])
        pending_deliveries = request.env['stocksense.delivery'].search_count([('state', 'in', ['draft', 'confirmed', 'assigned'])])
        pending_transfers = request.env['stocksense.transfer'].search_count([('state', 'in', ['draft', 'in_transit'])])

        # Verify audit chain integrity
        all_blocks = request.env['stocksense.audit.trail'].search([], order='sequence_number asc')
        record_list = [
            {
                'sequence_number': b.sequence_number,
                'previous_hash': b.previous_hash,
                'current_hash': b.current_hash,
                'payload': b.payload_json
            }
            for b in all_blocks
        ]
        audit_res = verify_chain(record_list)

        # Recent movements
        recent_ledger = request.env['stocksense.stock.ledger'].search([], order='date desc, id desc', limit=10)
        movements = [
            {
                'id': m.id,
                'name': m.name,
                'date': m.date.strftime('%Y-%m-%d %H:%M:%S') if m.date else '',
                'product_name': m.product_id.name,
                'product_sku': m.product_sku,
                'op_type': m.operation_type,
                'ref': m.reference_document,
                'delta': m.quantity_change,
                'balance_after': m.balance_after,
                'user': m.user_id.name
            }
            for m in recent_ledger
        ]

        # Critical / Attention Products
        critical_products = []
        for p in products.filtered(lambda p: p.health_status in ['attention', 'critical']):
            wh_names = list(set(filter(None, p.quant_ids.mapped('location_id.warehouse_id.name'))))
            wh_codes = list(set(filter(None, p.quant_ids.mapped('location_id.warehouse_id.code'))))
            wh_name = wh_names[0] if wh_names else (p.preferred_location_id.warehouse_id.name if p.preferred_location_id and p.preferred_location_id.warehouse_id else 'WH-MAIN')
            wh_code = wh_codes[0] if wh_codes else (p.preferred_location_id.warehouse_id.code if p.preferred_location_id and p.preferred_location_id.warehouse_id else 'WH')
            critical_products.append({
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'category_name': p.category_id.name if p.category_id else 'General',
                'uom': p.uom_name,
                'stock': round(p.total_stock, 1),
                'available_stock': round(p.available_stock, 1),
                'reserved_stock': round(p.total_stock - p.available_stock, 1),
                'cost_price': round(p.standard_price, 2),
                'valuation': round(p.stock_valuation, 2),
                'min_threshold': p.min_stock_threshold,
                'max_threshold': p.max_stock_threshold,
                'health_status': p.health_status,
                'health_score': p.health_score,
                'reasons': p.health_reasons,
                'days_of_inventory': round(p.days_of_inventory, 1) if p.days_of_inventory else None,
                'preferred_location': p.preferred_location_id.name if p.preferred_location_id else '',
                'warehouse_name': wh_name,
                'warehouse_code': wh_code
            })

        # Warehouse Breakdown
        warehouses = request.env['stocksense.warehouse'].search([])
        warehouse_stats = [
            {
                'id': wh.id,
                'name': wh.name,
                'code': wh.code,
                'total_stock': wh.total_stock,
                'sku_count': wh.sku_count,
                'critical_count': wh.critical_sku_count
            }
            for wh in warehouses
        ]

        # Movement Overview
        ledgers = request.env['stocksense.stock.ledger'].search([])
        inbound_total = sum(l.quantity_change for l in ledgers if l.operation_type == 'receipt')
        outbound_total = sum(abs(l.quantity_change) for l in ledgers if l.operation_type == 'delivery')
        completed_transfers = request.env['stocksense.transfer'].search([('state', '=', 'completed')])
        transfers_total = sum(completed_transfers.mapped('total_qty'))
        adjustments_total = sum(abs(l.quantity_change) for l in ledgers if l.operation_type == 'adjustment')

        # Anomalies & Operational Intelligence
        anomaly_alerts = request.env['stocksense.inventory.alert'].search([
            ('detection_mechanism', 'in', ['deterministic_rule', 'statistical_deviation']),
            ('state', 'in', ['new', 'acknowledged'])
        ])

        # Scan for pending delivery deficits
        pending_deliveries_recs = request.env['stocksense.delivery'].search([('state', 'in', ['draft', 'confirmed'])])
        delivery_deficits = []
        for d in pending_deliveries_recs:
            for line in d.line_ids:
                if line.product_id.total_stock < line.quantity_requested:
                    delivery_deficits.append({
                        'id': f"def_{d.id}_{line.id}",
                        'rule_code': 'delivery_deficit',
                        'anomaly_type': 'deterministic_rule',
                        'severity': 'critical',
                        'title': f'Deficit Attempt: {line.product_id.name}',
                        'description': f"Order {d.name} requests {line.quantity_requested:.1f} units, but only {line.product_id.total_stock:.1f} available in physical stock.",
                        'product_name': line.product_id.name,
                        'product_sku': line.product_id.sku,
                        'detected_at': d.date.strftime('%Y-%m-%d %H:%M:%S') if d.date else '',
                        'metrics': {'requested': line.quantity_requested, 'available': line.product_id.total_stock}
                    })

        anomalies_list = []
        for a in anomaly_alerts:
            anomalies_list.append({
                'id': a.id,
                'rule_code': a.alert_type,
                'anomaly_type': a.detection_mechanism,
                'severity': a.severity,
                'title': f"{a.name}: {a.product_id.name}",
                'description': a.reason,
                'product_name': a.product_id.name,
                'product_sku': a.product_sku,
                'detected_at': a.detected_at.strftime('%Y-%m-%d %H:%M:%S') if a.detected_at else '',
                'metrics': {'current_quantity': a.current_quantity, 'threshold': a.threshold}
            })
        anomalies_list.extend(delivery_deficits)

        # Audit Blocks
        recent_blocks = request.env['stocksense.audit.trail'].search([], order='sequence_number desc, id desc', limit=15)
        audit_block_list = [
            {
                'id': b.id,
                'sequence_number': b.sequence_number,
                'timestamp': b.timestamp.strftime('%Y-%m-%d %H:%M:%S') if b.timestamp else '',
                'event_type': b.event_type,
                'record_reference': b.record_reference,
                'previous_hash': b.previous_hash,
                'current_hash': b.current_hash,
                'is_verified': b.is_verified,
                'payload': b.payload_json
            }
            for b in recent_blocks
        ]

        # All Products for Simulator, Inventory Page, and Overview
        all_products_list = []
        for p in products:
            wh_ids = list(set(filter(None, p.quant_ids.mapped('location_id.warehouse_id.id'))))
            if not wh_ids and p.preferred_location_id and p.preferred_location_id.warehouse_id:
                wh_ids = [p.preferred_location_id.warehouse_id.id]
            wh_names = list(set(filter(None, p.quant_ids.mapped('location_id.warehouse_id.name'))))
            wh_codes = list(set(filter(None, p.quant_ids.mapped('location_id.warehouse_id.code'))))
            wh_name = wh_names[0] if wh_names else (p.preferred_location_id.warehouse_id.name if p.preferred_location_id and p.preferred_location_id.warehouse_id else 'WH-MAIN')
            wh_code = wh_codes[0] if wh_codes else (p.preferred_location_id.warehouse_id.code if p.preferred_location_id and p.preferred_location_id.warehouse_id else 'WH')

            all_products_list.append({
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'category_name': p.category_id.name if p.category_id else 'General',
                'uom': p.uom_name,
                'stock': round(p.total_stock, 1),
                'available_stock': round(p.available_stock, 1),
                'reserved_stock': round(p.total_stock - p.available_stock, 1),
                'cost_price': round(p.standard_price, 2),
                'valuation': round(p.stock_valuation, 2),
                'min_threshold': p.min_stock_threshold,
                'max_threshold': p.max_stock_threshold,
                'health_status': p.health_status,
                'health_score': p.health_score,
                'reasons': p.health_reasons,
                'days_of_inventory': round(p.days_of_inventory, 1) if p.days_of_inventory else None,
                'preferred_location': p.preferred_location_id.name if p.preferred_location_id else '',
                'warehouse_ids': wh_ids,
                'warehouse_name': wh_name,
                'warehouse_code': wh_code
            })

        # Open alerts detail
        open_alerts_list = [
            {
                'id': a.id,
                'name': a.name,
                'severity': a.severity,
                'alert_type': a.alert_type,
                'detection_mechanism': a.detection_mechanism,
                'product_id': a.product_id.id,
                'product_name': a.product_id.name,
                'product_sku': a.product_sku,
                'current_quantity': round(a.current_quantity, 1),
                'threshold': round(a.threshold, 1),
                'reason': a.reason,
                'detected_at': a.detected_at.strftime('%Y-%m-%d %H:%M:%S') if a.detected_at else ''
            }
            for a in open_alerts
        ]

        # Live Real-Time Stock Deficit Alerts
        # Ensure products in critical/attention state are surfaced as operational alerts if not already in alert records
        alert_product_ids = set(a.product_id.id for a in open_alerts)
        for p in products.filtered(lambda p: p.health_status in ['critical', 'attention'] and p.id not in alert_product_ids):
            clean_reason = p.health_reasons.strip().replace('\n• ', ' · ') if p.health_reasons else f"Stock level ({p.total_stock:.1f}) is at or below safety threshold ({p.min_stock_threshold:.1f})."
            if clean_reason.startswith('• '):
                clean_reason = clean_reason[2:]
            open_alerts_list.append({
                'id': f"live_alert_{p.id}",
                'name': f"LIVE-{p.sku}",
                'severity': p.health_status,
                'alert_type': 'low_stock',
                'detection_mechanism': 'threshold_breach',
                'product_id': p.id,
                'product_name': p.name,
                'product_sku': p.sku,
                'current_quantity': round(p.total_stock, 1),
                'threshold': round(p.min_stock_threshold, 1),
                'reason': clean_reason,
                'detected_at': 'Real-Time Telemetry'
            })

        # Calculate health percentages
        healthy_pct = round((healthy_count / total_products * 100), 1) if total_products else 0
        attention_pct = round((attention_count / total_products * 100), 1) if total_products else 0
        critical_pct = round((critical_count / total_products * 100), 1) if total_products else 0
        low_stock_count = len(products.filtered(lambda p: p.total_stock <= p.min_stock_threshold))

        return {
            'kpis': {
                'total_products': total_products,
                'total_stock': round(total_stock, 1),
                'available_stock': round(sum(products.mapped('available_stock')), 1),
                'total_valuation': round(total_valuation, 2),
                'healthy_count': healthy_count,
                'attention_count': attention_count,
                'critical_count': critical_count,
                'open_alerts_count': len(open_alerts_list),
                'pending_receipts': pending_receipts,
                'pending_deliveries': pending_deliveries,
                'pending_transfers': pending_transfers,
            },
            'movement_overview': {
                'inbound_total': round(inbound_total, 1),
                'outbound_total': round(outbound_total, 1),
                'transfers_total': round(transfers_total, 1),
                'adjustments_total': round(adjustments_total, 1)
            },
            'operational_intelligence': {
                'critical_count': critical_count,
                'attention_count': attention_count,
                'anomalies_count': len(anomalies_list),
                'low_stock_count': low_stock_count,
                'anomalies': anomalies_list,
                'active_alerts': open_alerts_list
            },
            'health_distribution': {
                'healthy_count': healthy_count,
                'healthy_pct': healthy_pct,
                'attention_count': attention_count,
                'attention_pct': attention_pct,
                'critical_count': critical_count,
                'critical_pct': critical_pct
            },
            'audit_integrity': {
                'valid': audit_res['valid'],
                'total_blocks': audit_res['total_verified'],
                'broken_at': audit_res.get('broken_at_sequence'),
                'error': audit_res.get('error_message'),
                'blocks': audit_block_list
            },
            'recent_movements': movements,
            'critical_products': critical_products,
            'all_products': all_products_list,
            'warehouse_stats': warehouse_stats
        }

    @http.route('/api/stocksense/simulate', type='json', auth='user', methods=['POST'])
    def run_simulation(self, product_id, scenario_type, quantity, **kwargs):
        """Run sandboxed What-If simulation via REST."""
        product = request.env['stocksense.product'].browse(int(product_id))
        if not product.exists():
            return {'error': 'Product not found'}

        res = simulate_hypothetical_scenario(
            current_stock=product.total_stock,
            min_threshold=product.min_stock_threshold,
            max_threshold=product.max_stock_threshold,
            scenario_type=scenario_type,
            quantity=float(quantity)
        )
        return {'success': True, 'result': res}
