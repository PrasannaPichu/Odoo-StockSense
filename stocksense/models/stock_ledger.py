# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class StocksenseStockLedger(models.Model):
    _name = 'stocksense.stock.ledger'
    _description = 'StockSense Immutable Stock Ledger'
    _order = 'date desc, id desc'

    name = fields.Char(string='Ledger Entry Ref', required=True, copy=False, readonly=True, index=True)
    date = fields.Datetime(string='Timestamp', default=fields.Datetime.now, required=True, index=True)
    product_id = fields.Many2one(
        'stocksense.product', string='Product', required=True, index=True, ondelete='restrict'
    )
    product_sku = fields.Char(related='product_id.sku', string='SKU', store=True, readonly=True)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Warehouse', index=True, ondelete='restrict'
    )
    location_src_id = fields.Many2one(
        'stocksense.location', string='Source Location', index=True
    )
    location_dest_id = fields.Many2one(
        'stocksense.location', string='Destination Location', index=True
    )
    operation_type = fields.Selection([
        ('receipt', 'Supplier Goods Receipt'),
        ('delivery', 'Customer Delivery Order'),
        ('transfer', 'Internal Stock Transfer'),
        ('adjustment', 'Physical Inventory Adjustment'),
    ], string='Operation Type', required=True, index=True)
    reference_document = fields.Char(string='Source Document', required=True, index=True)

    quantity_change = fields.Float(string='Quantity Change (Δ)', required=True, digits=(12, 2))
    balance_before = fields.Float(string='Balance Before', required=True, digits=(12, 2))
    balance_after = fields.Float(string='Balance After', required=True, digits=(12, 2))

    user_id = fields.Many2one(
        'res.users', string='Authorized By', default=lambda self: self.env.user, required=True
    )
    notes = fields.Text(string='Operational Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.stock.ledger') or _('New')
        return super(StocksenseStockLedger, self).create(vals_list)
