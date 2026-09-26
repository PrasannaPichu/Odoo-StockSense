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
        critical_products = [
            {
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'stock': p.total_stock,
                'min_threshold': p.min_stock_threshold,
                'health_status': p.health_status,
                'health_score': p.health_score,
                'reasons': p.health_reasons
            }
            for p in products.filtered(lambda p: p.health_status in ['attention', 'critical'])
        ]

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

        return {
            'kpis': {
                'total_products': total_products,
                'total_stock': round(total_stock, 1),
                'total_valuation': round(total_valuation, 2),
                'healthy_count': healthy_count,
                'attention_count': attention_count,
                'critical_count': critical_count,
                'open_alerts_count': len(open_alerts),
                'pending_receipts': pending_receipts,
                'pending_deliveries': pending_deliveries,
                'pending_transfers': pending_transfers,
            },
            'audit_integrity': {
                'valid': audit_res['valid'],
                'total_blocks': audit_res['total_verified'],
                'broken_at': audit_res.get('broken_at_sequence'),
                'error': audit_res.get('error_message')
            },
            'recent_movements': movements,
            'critical_products': critical_products,
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
