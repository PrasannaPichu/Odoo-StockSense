# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class StocksenseWarehouse(models.Model):
    _name = 'stocksense.warehouse'
    _description = 'StockSense Warehouse'
    _order = 'name asc'

    name = fields.Char(string='Warehouse Name', required=True)
    code = fields.Char(string='Short Code', size=10, required=True, index=True)
    address = fields.Text(string='Address / Location Details')
    active = fields.Boolean(string='Active', default=True)

    location_ids = fields.One2many(
        'stocksense.location', 'warehouse_id', string='Storage Locations'
    )
    total_stock = fields.Float(
        string='Total Physical Stock', compute='_compute_warehouse_metrics'
    )
    sku_count = fields.Integer(
        string='Active SKUs Stored', compute='_compute_warehouse_metrics'
    )
    critical_sku_count = fields.Integer(
        string='Critical SKUs', compute='_compute_warehouse_metrics'
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Warehouse code must be globally unique.')
    ]

    @api.depends('location_ids.quant_ids.quantity')
    def _compute_warehouse_metrics(self):
        for wh in self:
            internal_locations = wh.location_ids.filtered(lambda l: l.usage == 'internal')
            quants = internal_locations.mapped('quant_ids')
            wh.total_stock = sum(quants.mapped('quantity'))
            distinct_products = quants.filtered(lambda q: q.quantity > 0).mapped('product_id')
            wh.sku_count = len(distinct_products)
            wh.critical_sku_count = len(distinct_products.filtered(lambda p: p.health_status == 'critical'))


class StocksenseLocation(models.Model):
    _name = 'stocksense.location'
    _description = 'StockSense Inventory Location'
    _order = 'complete_name asc'
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = 'complete_name'

    name = fields.Char(string='Location Name', required=True)
    complete_name = fields.Char(
        string='Full Path', compute='_compute_complete_name', recursive=True, store=True
    )
    parent_id = fields.Many2one(
        'stocksense.location', string='Parent Location', index=True, ondelete='cascade'
    )
    child_ids = fields.One2many(
        'stocksense.location', 'parent_id', string='Sub-Locations'
    )
    parent_path = fields.Char(index=True, unaccent=False)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Warehouse', index=True, ondelete='restrict'
    )
    usage = fields.Selection([
        ('internal', 'Internal Physical Location'),
        ('supplier', 'Supplier Virtual Location'),
        ('customer', 'Customer Virtual Location'),
        ('inventory_loss', 'Inventory Loss / Scrap Virtual Location'),
        ('transit', 'Inter-Warehouse Transit Location'),
    ], string='Location Type', default='internal', required=True, index=True)
    barcode = fields.Char(string='Location Barcode', index=True)
    active = fields.Boolean(string='Active', default=True)

    quant_ids = fields.One2many(
        'stocksense.quant', 'location_id', string='Stock Quants'
    )
    total_quantity = fields.Float(
        string='Total Stored Stock', compute='_compute_total_quantity'
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for loc in self:
            if loc.parent_id and loc.parent_id.complete_name:
                loc.complete_name = f"{loc.parent_id.complete_name}/{loc.name}"
            elif loc.warehouse_id and loc.warehouse_id.code:
                loc.complete_name = f"{loc.warehouse_id.code}/{loc.name}"
            else:
                loc.complete_name = loc.name

    @api.depends('quant_ids.quantity')
    def _compute_total_quantity(self):
        for loc in self:
            loc.total_quantity = sum(loc.quant_ids.mapped('quantity'))

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('Error! You cannot create recursive locations.'))
