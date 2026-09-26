# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from ..services.health_engine import evaluate_product_health
from ..services.explainability_engine import generate_risk_explanation

class StocksenseProductCategory(models.Model):
    _name = 'stocksense.product.category'
    _description = 'StockSense Product Category'
    _parent_name = "parent_id"
    _order = 'name asc'

    name = fields.Char(string='Category Name', required=True)
    parent_id = fields.Many2one('stocksense.product.category', string='Parent Category', ondelete='cascade')
    child_ids = fields.One2many('stocksense.product.category', 'parent_id', string='Subcategories')
    product_ids = fields.One2many('stocksense.product', 'category_id', string='Products')
    product_count = fields.Integer(string='Product Count', compute='_compute_product_count')

    @api.depends('product_ids')
    def _compute_product_count(self):
        for cat in self:
            cat.product_count = len(cat.product_ids)


class StocksenseProduct(models.Model):
    _name = 'stocksense.product'
    _description = 'StockSense Product / SKU'
    _order = 'name asc'

    name = fields.Char(string='Product Name', required=True, index=True)
    sku = fields.Char(string='SKU / Internal Reference', required=True, index=True)
    category_id = fields.Many2one(
        'stocksense.product.category', string='Product Category', required=True, index=True
    )
    uom_name = fields.Char(string='Unit of Measure', default='Units', required=True)
    standard_price = fields.Float(string='Cost Price ($)', digits=(12, 2), default=0.0)
    list_price = fields.Float(string='Sales Price ($)', digits=(12, 2), default=0.0)

    min_stock_threshold = fields.Float(string='Minimum Stock Threshold', default=10.0, required=True)
    max_stock_threshold = fields.Float(string='Maximum Capacity Threshold', default=100.0)

    preferred_location_id = fields.Many2one(
        'stocksense.location', string='Preferred Default Location',
        domain="[('usage', '=', 'internal')]"
    )
    active = fields.Boolean(string='Active', default=True)

    # Physical Stock Metrics
    quant_ids = fields.One2many('stocksense.quant', 'product_id', string='Inventory Quants')
    ledger_ids = fields.One2many('stocksense.stock.ledger', 'product_id', string='Stock Ledger Entries')
    alert_ids = fields.One2many('stocksense.inventory.alert', 'product_id', string='Inventory Alerts')

    total_stock = fields.Float(
        string='Total On Hand', compute='_compute_stock_levels', store=True, index=True
    )
    available_stock = fields.Float(
        string='Free / Unreserved Stock', compute='_compute_stock_levels', store=True
    )
    stock_valuation = fields.Float(
        string='Inventory Valuation ($)', compute='_compute_stock_levels', store=True
    )

    # Health & Operational Intelligence
    health_status = fields.Selection([
        ('healthy', 'Healthy'),
        ('attention', 'Attention Required'),
        ('critical', 'Critical Risk'),
    ], string='Health Status', compute='_compute_inventory_health', store=True, default='healthy', index=True)
    health_score = fields.Float(string='Health Index (0-100)', compute='_compute_inventory_health', store=True)
    health_reasons = fields.Text(string='Health Explanations', compute='_compute_inventory_health', store=True)
    days_of_inventory = fields.Float(string='Days of Inventory Remaining', compute='_compute_inventory_health', store=True)

    _sql_constraints = [
        ('sku_unique', 'unique(sku)', 'Product SKU must be unique across the organization.')
    ]

    @api.depends('quant_ids.quantity', 'quant_ids.reserved_quantity', 'quant_ids.location_id.usage')
    def _compute_stock_levels(self):
        for prod in self:
            internal_quants = prod.quant_ids.filtered(lambda q: q.location_id.usage == 'internal')
            tot = sum(internal_quants.mapped('quantity'))
            res = sum(internal_quants.mapped('reserved_quantity'))
            prod.total_stock = tot
            prod.available_stock = tot - res
            prod.stock_valuation = tot * prod.standard_price

    @api.depends('total_stock', 'min_stock_threshold', 'max_stock_threshold')
    def _compute_inventory_health(self):
        for prod in self:
            eval_result = evaluate_product_health(
                current_stock=prod.total_stock,
                min_threshold=prod.min_stock_threshold,
                max_threshold=prod.max_stock_threshold
            )
            prod.health_status = eval_result['health_status']
            prod.health_score = eval_result['health_score']
            prod.days_of_inventory = eval_result.get('days_of_inventory') or 0.0
            prod.health_reasons = "\n• " + "\n• ".join(eval_result.get('explanations', []))

    def action_recompute_health(self):
        """Manual trigger to re-evaluate health with live consumption velocity."""
        self._compute_inventory_health()
        return True

    def action_view_stock_ledger(self):
        self.ensure_one()
        return {
            'name': _('Stock Ledger: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'stocksense.stock.ledger',
            'view_mode': 'tree,form',
            'domain': [('product_id', '=', self.id)],
            'context': {'default_product_id': self.id},
        }

    def action_open_simulator(self):
        self.ensure_one()
        return {
            'name': _('What-If Simulator: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'stocksense.simulation.scenario',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_id': self.id,
                'default_scenario_type': 'delivery',
                'default_quantity': 10.0,
            }
        }
