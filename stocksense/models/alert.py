# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class StocksenseInventoryAlert(models.Model):
    _name = 'stocksense.inventory.alert'
    _description = 'StockSense Operational Inventory Alert'
    _order = 'detected_at desc, id desc'

    name = fields.Char(string='Alert Ref', required=True, copy=False, readonly=True, index=True)
    product_id = fields.Many2one(
        'stocksense.product', string='Product / SKU', required=True, index=True, ondelete='cascade'
    )
    product_sku = fields.Char(related='product_id.sku', string='SKU', store=True, readonly=True)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Warehouse', index=True, ondelete='set null'
    )
    current_quantity = fields.Float(string='Current Stock Level', required=True, digits=(12, 2))
    threshold = fields.Float(string='Minimum Threshold Breached', required=True, digits=(12, 2))
    severity = fields.Selection([
        ('info', 'Informational'),
        ('warning', 'Warning (Low Stock)'),
        ('critical', 'Critical (Imminent Stock-Out)'),
    ], string='Severity Level', default='warning', required=True, index=True)
    reason = fields.Text(string='Causal Diagnosis & Reasoning', required=True)
    state = fields.Selection([
        ('new', 'Active Alert'),
        ('acknowledged', 'Acknowledged by Supervisor'),
        ('resolved', 'Resolved / Stock Replenished'),
    ], string='Status', default='new', required=True, index=True)
    detected_at = fields.Datetime(string='Detected At', default=fields.Datetime.now, required=True, index=True)
    acknowledged_by = fields.Many2one('res.users', string='Acknowledged By')
    resolved_by = fields.Many2one('res.users', string='Resolved By')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.inventory.alert') or _('New')
        return super(StocksenseInventoryAlert, self).create(vals_list)

    def action_acknowledge(self):
        self.write({
            'state': 'acknowledged',
            'acknowledged_by': self.env.user.id
        })
        return True

    def action_resolve(self):
        self.write({
            'state': 'resolved',
            'resolved_by': self.env.user.id
        })
        return True
