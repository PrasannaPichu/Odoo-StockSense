# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from ..services.kafka_producer import TOPIC_EVENTS

class StocksenseReceipt(models.Model):
    _name = 'stocksense.receipt'
    _description = 'StockSense Inbound Goods Receipt'
    _order = 'date desc, id desc'

    name = fields.Char(string='Receipt Ref', required=True, copy=False, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Supplier / Vendor', required=True, index=True)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Destination Warehouse', required=True, index=True
    )
    location_dest_id = fields.Many2one(
        'stocksense.location', string='Destination Bay / Rack', required=True,
        domain="[('warehouse_id', '=', warehouse_id), ('usage', '=', 'internal')]"
    )
    date = fields.Datetime(string='Receipt Date', default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft Order'),
        ('confirmed', 'Confirmed / Awaiting Goods'),
        ('validated', 'Received & Stored'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, index=True)

    line_ids = fields.One2many('stocksense.receipt.line', 'receipt_id', string='Receipt Line Items')
    total_qty = fields.Float(string='Total Items Received', compute='_compute_total_qty', store=True)
    notes = fields.Text(string='Receiving Bay Notes')

    @api.depends('line_ids.quantity_received')
    def _compute_total_qty(self):
        for rec in self:
            rec.total_qty = sum(rec.line_ids.mapped('quantity_received'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.receipt') or _('New')
        return super(StocksenseReceipt, self).create(vals_list)

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one product line item before confirming.'))
            rec.write({'state': 'confirmed'})
        return True

    def action_validate(self):
        """
        Validate Goods Receipt:
        1. Atomically increment physical stock quants.
        2. Create immutable double-entry stock ledger record.
        3. Append tamper-evident SHA-256 audit block.
        4. Stream RECEIPT_VALIDATED event to Kafka (or resilient outbox).
        5. Re-evaluate inventory health & auto-resolve stock-out alerts.
        """
        self.ensure_one()
        if self.state == 'validated':
            raise UserError(_('This receipt has already been validated.'))
        if self.state == 'cancelled':
            raise UserError(_('Cancelled receipts cannot be validated.'))

        supplier_loc = self.env['stocksense.location'].search([('usage', '=', 'supplier')], limit=1)
        if not supplier_loc:
            supplier_loc = self.env['stocksense.location'].create({
                'name': 'Suppliers',
                'complete_name': 'Virtual Locations/Suppliers',
                'usage': 'supplier'
            })

        for line in self.line_ids:
            if line.quantity_received <= 0:
                raise ValidationError(
                    _('Received quantity for %s must be strictly positive.') % line.product_id.name
                )

            # 1. Update Quant
            quant, prev_bal, new_bal = self.env['stocksense.quant'].update_stock_quant(
                product_id=line.product_id.id,
                location_id=self.location_dest_id.id,
                delta_quantity=line.quantity_received
            )

            # 2. Immutable Ledger Entry
            self.env['stocksense.stock.ledger'].sudo().create({
                'product_id': line.product_id.id,
                'warehouse_id': self.warehouse_id.id,
                'location_src_id': supplier_loc.id,
                'location_dest_id': self.location_dest_id.id,
                'operation_type': 'receipt',
                'reference_document': self.name,
                'quantity_change': line.quantity_received,
                'balance_before': prev_bal,
                'balance_after': new_bal,
                'user_id': self.env.user.id,
                'notes': f"Received from {self.partner_id.name}"
            })

            # 3. Audit Block
            audit_payload = {
                'operation': 'RECEIPT_VALIDATED',
                'reference': self.name,
                'supplier': self.partner_id.name,
                'product_id': line.product_id.id,
                'product_sku': line.product_id.sku,
                'warehouse': self.warehouse_id.code,
                'location': self.location_dest_id.complete_name,
                'quantity': line.quantity_received,
                'balance_before': prev_bal,
                'balance_after': new_bal,
                'user': self.env.user.name
            }
            self.env['stocksense.audit.trail'].sudo().append_audit_block(
                event_type='RECEIPT_VALIDATED',
                record_reference=self.name,
                payload=audit_payload
            )

            # 4. Kafka Event Stream
            self.env['stocksense.event.outbox'].sudo().queue_or_publish_event(
                topic=TOPIC_EVENTS,
                event_type='RECEIPT_VALIDATED',
                payload=audit_payload,
                partition_key=str(line.product_id.id)
            )

            # 5. Health & Alert Updates
            line.product_id.action_recompute_health()
            if line.product_id.total_stock > line.product_id.min_stock_threshold:
                open_alerts = self.env['stocksense.inventory.alert'].search([
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'new')
                ])
                open_alerts.action_resolve()

        self.write({'state': 'validated'})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'validated':
                raise UserError(_('Cannot cancel a validated receipt. Create an adjustment or return instead.'))
            rec.write({'state': 'cancelled'})
        return True


class StocksenseReceiptLine(models.Model):
    _name = 'stocksense.receipt.line'
    _description = 'StockSense Receipt Line Item'

    receipt_id = fields.Many2one('stocksense.receipt', string='Receipt', required=True, ondelete='cascade')
    product_id = fields.Many2one('stocksense.product', string='Product', required=True)
    product_sku = fields.Char(related='product_id.sku', string='SKU', readonly=True)
    uom_name = fields.Char(related='product_id.uom_name', string='UoM', readonly=True)
    quantity_expected = fields.Float(string='Ordered Qty', default=1.0, required=True)
    quantity_received = fields.Float(string='Received Qty', default=1.0, required=True)
