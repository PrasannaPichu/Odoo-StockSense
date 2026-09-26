# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class StocksenseQuant(models.Model):
    _name = 'stocksense.quant'
    _description = 'StockSense Physical Stock Quant'
    _order = 'location_id asc, product_id asc'

    product_id = fields.Many2one(
        'stocksense.product', string='Product', required=True, index=True, ondelete='cascade'
    )
    product_sku = fields.Char(related='product_id.sku', string='SKU', store=True, readonly=True)
    location_id = fields.Many2one(
        'stocksense.location', string='Location', required=True, index=True, ondelete='restrict'
    )
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', related='location_id.warehouse_id', string='Warehouse',
        store=True, readonly=True, index=True
    )
    quantity = fields.Float(string='Physical Quantity', required=True, default=0.0, digits=(12, 2))
    reserved_quantity = fields.Float(string='Reserved Quantity', default=0.0, digits=(12, 2))
    available_quantity = fields.Float(
        string='Available Quantity', compute='_compute_available_quantity', store=True
    )

    _sql_constraints = [
        ('product_location_unique', 'unique(product_id, location_id)',
         'A stock quant must be unique for each product and location combination.')
    ]

    @api.depends('quantity', 'reserved_quantity')
    def _compute_available_quantity(self):
        for quant in self:
            quant.available_quantity = quant.quantity - quant.reserved_quantity

    @api.model
    def update_stock_quant(self, product_id, location_id, delta_quantity):
        """
        Atomically update or create physical stock quant for (product_id, location_id).
        Returns:
            tuple: (quant_record, previous_qty, new_qty)
        """
        quant = self.search([
            ('product_id', '=', product_id),
            ('location_id', '=', location_id)
        ], limit=1)

        delta = float(delta_quantity)
        if quant:
            prev_qty = quant.quantity
            new_qty = prev_qty + delta
            quant.write({'quantity': new_qty})
        else:
            prev_qty = 0.0
            new_qty = delta
            quant = self.create({
                'product_id': product_id,
                'location_id': location_id,
                'quantity': new_qty
            })

        return quant, prev_qty, new_qty
