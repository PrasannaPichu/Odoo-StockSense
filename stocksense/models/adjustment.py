# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from ..services.kafka_producer import TOPIC_EVENTS, TOPIC_ALERTS

class StocksenseAdjustment(models.Model):
    _name = 'stocksense.adjustment'
    _description = 'StockSense Physical Inventory Adjustment'
    _order = 'date desc, id desc'

    name = fields.Char(string='Adjustment Ref', required=True, copy=False, readonly=True, index=True)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Warehouse', required=True, index=True
    )
    location_id = fields.Many2one(
        'stocksense.location', string='Physical Count Location', required=True,
        domain="[('warehouse_id', '=', warehouse_id), ('usage', '=', 'internal')]"
    )
    reason = fields.Selection([
        ('damage', 'Physical Damage / Broken Goods'),
        ('missing', 'Shrinkage / Unexplained Loss'),
        ('counting_error', 'Cycle Count / Human Measurement Correction'),
        ('expired', 'Expired / Degraded Shelf Life'),
        ('other', 'Other Operational Reason'),
    ], string='Mandatory Reason for Adjustment', required=True, default='counting_error', index=True)
    date = fields.Datetime(string='Audit Timestamp', default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft Audit'),
        ('validated', 'Applied to Physical Stock'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, index=True)

    line_ids = fields.One2many('stocksense.adjustment.line', 'adjustment_id', string='Count Discrepancies')
    notes = fields.Text(string='Auditor Comments')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.adjustment') or _('New')
        return super(StocksenseAdjustment, self).create(vals_list)

    def action_validate(self):
        """
        Validate Physical Adjustment:
        1. Set quant directly to counted quantity (difference applied as delta).
        2. Create immutable stock ledger entry with exact discrepancy Δ.
        3. Append tamper-evident SHA-256 audit block.
        4. Detect repeated adjustments pattern (Anomaly Rule).
        5. Stream STOCK_ADJUSTED event to Kafka.
        """
        self.ensure_one()
        if self.state == 'validated':
            raise UserError(_('This inventory adjustment has already been validated.'))
        if self.state == 'cancelled':
            raise UserError(_('Cancelled adjustments cannot be validated.'))
        if not self.line_ids:
            raise UserError(_('Please add at least one product count line item.'))

        loss_loc = self.env['stocksense.location'].search([('usage', '=', 'inventory_loss')], limit=1)
        if not loss_loc:
            loss_loc = self.env['stocksense.location'].create({
                'name': 'Inventory Loss & Scrap',
                'complete_name': 'Virtual Locations/Inventory Loss',
                'usage': 'inventory_loss'
            })

        for line in self.line_ids:
            delta = line.counted_qty - line.recorded_qty

            # 1. Update Quant
            quant, prev_bal, new_bal = self.env['stocksense.quant'].update_stock_quant(
                product_id=line.product_id.id,
                location_id=self.location_id.id,
                delta_quantity=delta
            )

            # 2. Immutable Ledger Entry
            src_loc = self.location_id if delta < 0 else loss_loc
            dst_loc = loss_loc if delta < 0 else self.location_id

            self.env['stocksense.stock.ledger'].sudo().create({
                'product_id': line.product_id.id,
                'warehouse_id': self.warehouse_id.id,
                'location_src_id': src_loc.id,
                'location_dest_id': dst_loc.id,
                'operation_type': 'adjustment',
                'reference_document': self.name,
                'quantity_change': delta,
                'balance_before': prev_bal,
                'balance_after': new_bal,
                'user_id': self.env.user.id,
                'notes': f"Adjustment reason: {dict(self._fields['reason'].selection).get(self.reason)}"
            })

            # 3. Audit Block
            audit_payload = {
                'operation': 'STOCK_ADJUSTED',
                'reference': self.name,
                'reason': self.reason,
                'product_id': line.product_id.id,
                'product_sku': line.product_id.sku,
                'warehouse': self.warehouse_id.code,
                'location': self.location_id.complete_name,
                'recorded_qty': line.recorded_qty,
                'counted_qty': line.counted_qty,
                'discrepancy_delta': delta,
                'user': self.env.user.name
            }
            self.env['stocksense.audit.trail'].sudo().append_audit_block(
                event_type='STOCK_ADJUSTED',
                record_reference=self.name,
                payload=audit_payload
            )

            # 4. Anomaly Check for Repeated Discrepancies
            recent_adjs = self.env['stocksense.adjustment.line'].search([
                ('product_id', '=', line.product_id.id),
                ('adjustment_id.state', '=', 'validated')
            ], limit=5)
            if len(recent_adjs) >= 2:
                total_loss = sum(abs(a.discrepancy_qty) for a in recent_adjs) + abs(delta)
                self.env['stocksense.inventory.alert'].sudo().create({
                    'product_id': line.product_id.id,
                    'warehouse_id': self.warehouse_id.id,
                    'current_quantity': line.product_id.total_stock,
                    'threshold': line.product_id.min_stock_threshold,
                    'severity': 'critical' if total_loss > 10 else 'warning',
                    'alert_type': 'repeated_adjustments',
                    'detection_mechanism': 'deterministic_rule',
                    'reason': f"Multiple inventory adjustments detected for {line.product_id.name} ({len(recent_adjs) + 1} occurrences, total variance: {total_loss:.1f} units). Potential shrinkage or inaccurate receipts."
                })

            # 5. Kafka Event Stream
            self.env['stocksense.event.outbox'].sudo().queue_or_publish_event(
                topic=TOPIC_EVENTS,
                event_type='STOCK_ADJUSTED',
                payload=audit_payload,
                partition_key=str(line.product_id.id)
            )

            # 6. Recompute product health
            line.product_id.action_recompute_health()

        self.write({'state': 'validated'})
        return True

    def action_cancel(self):
        for adj in self:
            if adj.state == 'validated':
                raise UserError(_('Cannot cancel a validated physical inventory adjustment.'))
            adj.write({'state': 'cancelled'})
        return True


class StocksenseAdjustmentLine(models.Model):
    _name = 'stocksense.adjustment.line'
    _description = 'StockSense Physical Count Line Item'

    adjustment_id = fields.Many2one('stocksense.adjustment', string='Adjustment', required=True, ondelete='cascade')
    product_id = fields.Many2one('stocksense.product', string='Product / SKU', required=True)
    product_sku = fields.Char(related='product_id.sku', string='SKU', readonly=True)
    recorded_qty = fields.Float(string='Recorded System Stock', digits=(12, 2), readonly=True)
    counted_qty = fields.Float(string='Physical Counted Qty', digits=(12, 2), required=True)
    discrepancy_qty = fields.Float(
        string='Discrepancy (Δ)', compute='_compute_discrepancy', store=True, digits=(12, 2)
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.adjustment_id.location_id:
            quant = self.env['stocksense.quant'].search([
                ('product_id', '=', self.product_id.id),
                ('location_id', '=', self.adjustment_id.location_id.id)
            ], limit=1)
            self.recorded_qty = quant.quantity if quant else 0.0
            self.counted_qty = self.recorded_qty

    @api.depends('recorded_qty', 'counted_qty')
    def _compute_discrepancy(self):
        for line in self:
            line.discrepancy_qty = line.counted_qty - line.recorded_qty
