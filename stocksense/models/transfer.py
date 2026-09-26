# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from ..services.kafka_producer import TOPIC_EVENTS

class StocksenseTransfer(models.Model):
    _name = 'stocksense.transfer'
    _description = 'StockSense Internal Stock Transfer'
    _order = 'date desc, id desc'

    name = fields.Char(string='Transfer Ref', required=True, copy=False, readonly=True, index=True)
    location_src_id = fields.Many2one(
        'stocksense.location', string='Source Location', required=True,
        domain="[('usage', '=', 'internal')]"
    )
    location_dest_id = fields.Many2one(
        'stocksense.location', string='Destination Location', required=True,
        domain="[('usage', '=', 'internal')]"
    )
    warehouse_src_id = fields.Many2one(
        'stocksense.warehouse', related='location_src_id.warehouse_id', string='Source Warehouse',
        store=True, readonly=True
    )
    warehouse_dest_id = fields.Many2one(
        'stocksense.warehouse', related='location_dest_id.warehouse_id', string='Destination Warehouse',
        store=True, readonly=True
    )
    date = fields.Datetime(string='Transfer Date', default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft Transfer'),
        ('in_transit', 'In Transit'),
        ('completed', 'Completed & Transferred'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, index=True)

    line_ids = fields.One2many('stocksense.transfer.line', 'transfer_id', string='Transfer Items')
    total_qty = fields.Float(string='Total Units Relocated', compute='_compute_total_qty', store=True)
    notes = fields.Text(string='Internal Transfer Justification')

    @api.depends('line_ids.quantity')
    def _compute_total_qty(self):
        for trf in self:
            trf.total_qty = sum(trf.line_ids.mapped('quantity'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.transfer') or _('New')
        return super(StocksenseTransfer, self).create(vals_list)

    @api.constrains('location_src_id', 'location_dest_id')
    def _check_locations(self):
        for trf in self:
            if trf.location_src_id == trf.location_dest_id:
                raise ValidationError(_('Source and destination locations cannot be identical.'))

    def action_start_transit(self):
        for trf in self:
            if not trf.line_ids:
                raise UserError(_('Please specify at least one product line for internal transfer.'))
            for line in trf.line_ids:
                quant = self.env['stocksense.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', trf.location_src_id.id)
                ], limit=1)
                avail = quant.quantity if quant else 0.0
                if avail < line.quantity:
                    raise UserError(
                        _("Insufficient stock at %s to transfer %s units of %s (Available: %s).")
                        % (trf.location_src_id.complete_name, line.quantity, line.product_id.name, avail)
                    )
            trf.write({'state': 'in_transit'})
        return True

    def action_confirm(self):
        """Confirm internal transfer and initiate transit."""
        return self.action_start_transit()

    def action_complete(self):
        """
        Complete Internal Transfer:
        1. Decrement source location stock quant.
        2. Increment destination location stock quant.
        Total company-wide inventory balance remains INVARIANT (Δ = 0).
        3. Create mirrored immutable ledger entries.
        4. Append tamper-evident SHA-256 audit block.
        5. Emit TRANSFER_COMPLETED event to Kafka.
        """
        self.ensure_one()
        if self.state == 'completed':
            raise UserError(_('This transfer is already completed.'))
        if self.state == 'cancelled':
            raise UserError(_('Cancelled transfers cannot be completed.'))

        for line in self.line_ids:
            if line.quantity <= 0:
                raise ValidationError(_('Transfer quantity must be strictly positive.'))

            # 1. Update Source Quant (-qty)
            src_quant, src_prev, src_new = self.env['stocksense.quant'].update_stock_quant(
                product_id=line.product_id.id,
                location_id=self.location_src_id.id,
                delta_quantity=-line.quantity
            )

            # 2. Update Destination Quant (+qty)
            dst_quant, dst_prev, dst_new = self.env['stocksense.quant'].update_stock_quant(
                product_id=line.product_id.id,
                location_id=self.location_dest_id.id,
                delta_quantity=line.quantity
            )

            # 3. Create Immutable Ledger Entries
            # Outbound leg
            self.env['stocksense.stock.ledger'].sudo().create({
                'product_id': line.product_id.id,
                'warehouse_id': self.warehouse_src_id.id if self.warehouse_src_id else False,
                'location_src_id': self.location_src_id.id,
                'location_dest_id': self.location_dest_id.id,
                'operation_type': 'transfer',
                'reference_document': self.name,
                'quantity_change': -line.quantity,
                'balance_before': src_prev,
                'balance_after': src_new,
                'user_id': self.env.user.id,
                'notes': f"Transfer Outbound -> {self.location_dest_id.complete_name}"
            })
            # Inbound leg
            self.env['stocksense.stock.ledger'].sudo().create({
                'product_id': line.product_id.id,
                'warehouse_id': self.warehouse_dest_id.id if self.warehouse_dest_id else False,
                'location_src_id': self.location_src_id.id,
                'location_dest_id': self.location_dest_id.id,
                'operation_type': 'transfer',
                'reference_document': self.name,
                'quantity_change': line.quantity,
                'balance_before': dst_prev,
                'balance_after': dst_new,
                'user_id': self.env.user.id,
                'notes': f"Transfer Inbound <- {self.location_src_id.complete_name}"
            })

            # 4. Audit Block
            audit_payload = {
                'operation': 'TRANSFER_COMPLETED',
                'reference': self.name,
                'product_id': line.product_id.id,
                'product_sku': line.product_id.sku,
                'src_warehouse': self.warehouse_src_id.code if self.warehouse_src_id else 'N/A',
                'src_location': self.location_src_id.complete_name,
                'dst_warehouse': self.warehouse_dest_id.code if self.warehouse_dest_id else 'N/A',
                'dst_location': self.location_dest_id.complete_name,
                'quantity': line.quantity,
                'user': self.env.user.name
            }
            self.env['stocksense.audit.trail'].sudo().append_audit_block(
                event_type='TRANSFER_COMPLETED',
                record_reference=self.name,
                payload=audit_payload
            )

            # 5. Kafka Event Stream
            self.env['stocksense.event.outbox'].sudo().queue_or_publish_event(
                topic=TOPIC_EVENTS,
                event_type='TRANSFER_COMPLETED',
                payload=audit_payload,
                partition_key=str(line.product_id.id)
            )

        self.write({'state': 'completed'})
        return True

    def action_cancel(self):
        for trf in self:
            if trf.state == 'completed':
                raise UserError(_('Cannot cancel a completed internal transfer.'))
            trf.write({'state': 'cancelled'})
        return True


class StocksenseTransferLine(models.Model):
    _name = 'stocksense.transfer.line'
    _description = 'StockSense Transfer Line Item'

    transfer_id = fields.Many2one('stocksense.transfer', string='Transfer', required=True, ondelete='cascade')
    product_id = fields.Many2one('stocksense.product', string='Product', required=True)
    product_sku = fields.Char(related='product_id.sku', string='SKU', readonly=True)
    uom_name = fields.Char(related='product_id.uom_name', string='UoM', readonly=True)
    quantity = fields.Float(string='Transfer Quantity', default=1.0, required=True)
