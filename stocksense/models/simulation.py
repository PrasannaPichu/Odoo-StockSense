# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from ..services.simulator_engine import simulate_hypothetical_scenario

class StocksenseSimulationScenario(models.Model):
    _name = 'stocksense.simulation.scenario'
    _description = 'StockSense What-If Inventory Simulation Scenario'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Scenario Title', required=True, default='Hypothetical Operation Simulation')
    product_id = fields.Many2one('stocksense.product', string='Target Product / SKU', required=True)
    product_sku = fields.Char(related='product_id.sku', string='SKU', readonly=True)

    scenario_type = fields.Selection([
        ('delivery', 'Hypothetical Customer Order Dispatch'),
        ('receipt', 'Hypothetical Supplier Delivery Inflow'),
        ('transfer', 'Hypothetical Location Rebalance Transfer'),
    ], string='Scenario Type', default='delivery', required=True)

    simulated_quantity = fields.Float(string='Hypothetical Quantity', default=10.0, required=True)

    # Current Real State (Read-Only Baseline)
    current_stock = fields.Float(string='Current Actual Stock', readonly=True)
    min_threshold = fields.Float(string='Minimum Safety Threshold', readonly=True)
    max_threshold = fields.Float(string='Maximum Capacity Threshold', readonly=True)
    current_health_status = fields.Char(string='Current Health Status', readonly=True)
    current_health_score = fields.Float(string='Current Health Index', readonly=True)

    # Projected Sandboxed State (Computed In-Memory)
    projected_stock = fields.Float(string='Projected Resulting Stock', readonly=True)
    stock_delta = fields.Float(string='Simulated Net Delta (Δ)', readonly=True)
    projected_health_status = fields.Char(string='Projected Health Status', readonly=True)
    projected_health_score = fields.Float(string='Projected Health Index', readonly=True)
    health_transition = fields.Char(string='Health Shift', readonly=True)

    warnings = fields.Text(string='Operational Warnings / Risks', readonly=True)
    recommendations = fields.Text(string='Decision Support Guidance', readonly=True)
    is_simulated = fields.Boolean(string='Calculated', default=False)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.current_stock = self.product_id.total_stock
            self.min_threshold = self.product_id.min_stock_threshold
            self.max_threshold = self.product_id.max_stock_threshold
            self.current_health_status = (self.product_id.health_status or 'healthy').upper()
            self.current_health_score = self.product_id.health_score

    def action_run_simulation(self):
        """
        Run in-memory What-If calculation.
        CRITICAL: Never writes or touches actual stocksense.quant or ledger tables!
        """
        self.ensure_one()
        if not self.product_id:
            raise UserError(_('Please select a target product.'))

        res = simulate_hypothetical_scenario(
            current_stock=self.product_id.total_stock,
            min_threshold=self.product_id.min_stock_threshold,
            max_threshold=self.product_id.max_stock_threshold,
            scenario_type=self.scenario_type,
            quantity=self.simulated_quantity
        )

        h_impact = res['health_impact']
        bef = h_impact['before']
        aft = h_impact['after']

        self.write({
            'current_stock': res['current_stock'],
            'min_threshold': self.product_id.min_stock_threshold,
            'max_threshold': self.product_id.max_stock_threshold,
            'current_health_status': bef['health_status'].upper(),
            'current_health_score': bef['health_score'],
            'projected_stock': res['projected_stock'],
            'stock_delta': res['stock_delta'],
            'projected_health_status': aft['health_status'].upper(),
            'projected_health_score': aft['health_score'],
            'health_transition': h_impact['transition'],
            'warnings': "\n• " + "\n• ".join(res['warnings']) if res['warnings'] else "✓ No operational risks or threshold breaches projected.",
            'recommendations': "\n• " + "\n• ".join(res['recommendations']) if res['recommendations'] else "Proceed with standard warehouse fulfillment.",
            'is_simulated': True
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stocksense.simulation.scenario',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
