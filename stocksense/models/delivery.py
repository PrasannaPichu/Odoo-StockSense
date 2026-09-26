# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from ..services.kafka_producer import TOPIC_EVENTS, TOPIC_ALERTS
from ..services.anomaly_engine import detect_operational_anomalies

class StocksenseDelivery(models.Model):
    _name = 'stocksense.delivery'
    _description = 'StockSense Outbound Delivery Order'
    _order = 'date desc, id desc'

    name = fields.Char(string='Delivery Ref', required=True, copy=False, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, index=True)
    warehouse_id = fields.Many2one(
        'stocksense.warehouse', string='Dispatch Warehouse', required=True, index=True
    )
    location_src_id = fields.Many2one(
        'stocksense.location', string='Source Bay / Rack', required=True,
        domain="[('warehouse_id', '=', warehouse_id), ('usage', '=', 'internal')]"
    )
    date = fields.Datetime(string='Scheduled Date', default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft Order'),
        ('confirmed', 'Confirmed'),
        ('assigned', 'Stock Reserved / Picked'),
        ('validated', 'Dispatched / Delivered'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, index=True)

    line_ids = fields.One2many('stocksense.delivery.line', 'delivery_id', string='Delivery Items')
    total_qty = fields.Float(string='Total Dispatched Qty', compute='_compute_total_qty', store=True)
    notes = fields.Text(string='Shipping & Dispatch Notes')

    @api.depends('line_ids.quantity_delivered')
    def _compute_total_qty(self):
        for deliv in self:
            deliv.total_qty = sum(deliv.line_ids.mapped('quantity_delivered'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.delivery') or _('New')
        return super(StocksenseDelivery, self).create(vals_list)

    def action_confirm(self):
        for deliv in self:
            if not deliv.line_ids:
                raise UserError(_('Please add at least one line item to this delivery order.'))
            deliv.write({'state': 'confirmed'})
        return True

    def action_assign(self):
        """Check availability and mark as assigned."""
        for deliv in self:
            for line in deliv.line_ids:
                quant = self.env['stocksense.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', deliv.location_src_id.id)
                ], limit=1)
                available = quant.quantity if quant else 0.0
                if available < line.quantity_delivered:
                    raise UserError(
                        _("Insufficient stock for %s at %s. Requested: %s, Available: %s")
                        % (line.product_id.name, deliv.location_src_id.complete_name, line.quantity_delivered, available)
                    )
            deliv.write({'state': 'assigned'})
        return True

    def action_validate(self):
        """
        Validate Delivery:
        1. Ensure stock availability at the specific source location.
        2. Atomically decrement physical stock quants.
        3. Create immutable stock ledger record.
        4. Append tamper-evident SHA-256 audit block.
        5. Evaluate anomaly detection rules (velocity spikes, surges).
        6. Evaluate low-stock threshold and generate alerts if breached.
        7. Stream DELIVERY_VALIDATED event to Kafka.
        """
        self.ensure_one()
        if self.state == 'validated':
            raise UserError(_('This delivery order has already been validated.'))
        if self.state == 'cancelled':
            raise UserError(_('Cancelled delivery orders cannot be validated.'))

        customer_loc = self.env['stocksense.location'].search([('usage', '=', 'customer')], limit=1)
        if not customer_loc:
            customer_loc = self.env['stocksense.location'].create({
                'name': 'Customers',
                'complete_name': 'Virtual Locations/Customers',
                'usage': 'customer'
            })

        for line in self.line_ids:
            if line.quantity_delivered <= 0:
                raise ValidationError(
                    _('Delivered quantity for %s must be strictly positive.') % line.product_id.name
                )

            # Check Quant Availability
            quant = self.env['stocksense.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.location_src_id.id)
            ], limit=1)
            avail_stock = quant.quantity if quant else 0.0

            if line.quantity_delivered > avail_stock:
                raise ValidationError(
                    _("Cannot validate delivery! Requested %s units of '%s', but location '%s' only has %s units.")
                    % (line.quantity_delivered, line.product_id.name, self.location_src_id.complete_name, avail_stock)
                )

            # Anomaly Evaluation
            # Gather past deliveries for historical baseline
            past_moves = self.env['stocksense.stock.ledger'].search([
                ('product_id', '=', line.product_id.id),
                ('operation_type', '=', 'delivery')
            ], limit=30)
            hist_qtys = [abs(m.quantity_change) for m in past_moves]

            detected_anomalies = detect_operational_anomalies(
                product_sku=line.product_id.sku,
                current_operation_type='delivery',
                operation_quantity=line.quantity_delivered,
                available_stock=avail_stock,
                historical_movements_qty=hist_qtys
            )

            RULE_ALERT_MAP = {
                'RULE_INSUFFICIENT_STOCK': 'delivery_deficit',
                'RULE_REPEATED_ADJUSTMENTS': 'repeated_adjustments',
                'RULE_DORMANT_STOCK_SURGE': 'dormant_reactivation',
                'STAT_OUTBOUND_SURGE_Z3': 'outbound_surge',
                'STAT_OUTBOUND_SURGE_Z2': 'outbound_surge',
            }

            for anomaly in detected_anomalies:
                rule_code = anomaly.get('rule_code', '')
                a_type = RULE_ALERT_MAP.get(rule_code, 'general')
                det_mech = anomaly.get('anomaly_type', 'deterministic_rule')
                self.env['stocksense.inventory.alert'].sudo().create({
                    'product_id': line.product_id.id,
                    'warehouse_id': self.warehouse_id.id,
                    'current_quantity': avail_stock,
                    'threshold': line.product_id.min_stock_threshold,
                    'severity': anomaly['severity'],
                    'alert_type': a_type,
                    'detection_mechanism': det_mech,
                    'reason': f"[{anomaly['title']}] {anomaly['description']}"
                })

            # 1. Update Quant
            quant, prev_bal, new_bal = self.env['stocksense.quant'].update_stock_quant(
                product_id=line.product_id.id,
                location_id=self.location_src_id.id,
                delta_quantity=-line.quantity_delivered
            )

            # 2. Immutable Ledger Entry
            self.env['stocksense.stock.ledger'].sudo().create({
                'product_id': line.product_id.id,
                'warehouse_id': self.warehouse_id.id,
                'location_src_id': self.location_src_id.id,
                'location_dest_id': customer_loc.id,
                'operation_type': 'delivery',
                'reference_document': self.name,
                'quantity_change': -line.quantity_delivered,
                'balance_before': prev_bal,
                'balance_after': new_bal,
                'user_id': self.env.user.id,
                'notes': f"Dispatched to customer {self.partner_id.name}"
            })

            # 3. Audit Block
            audit_payload = {
                'operation': 'DELIVERY_VALIDATED',
                'reference': self.name,
                'customer': self.partner_id.name,
                'product_id': line.product_id.id,
                'product_sku': line.product_id.sku,
                'warehouse': self.warehouse_id.code,
                'location': self.location_src_id.complete_name,
                'quantity': line.quantity_delivered,
                'balance_before': prev_bal,
                'balance_after': new_bal,
                'user': self.env.user.name
            }
            self.env['stocksense.audit.trail'].sudo().append_audit_block(
                event_type='DELIVERY_VALIDATED',
                record_reference=self.name,
                payload=audit_payload
            )

            # 4. Kafka Event Stream
            self.env['stocksense.event.outbox'].sudo().queue_or_publish_event(
                topic=TOPIC_EVENTS,
                event_type='DELIVERY_VALIDATED',
                payload=audit_payload,
                partition_key=str(line.product_id.id)
            )

            # 5. Low-Stock Alert Generation if stock drops below threshold
            line.product_id.action_recompute_health()
            if line.product_id.total_stock <= line.product_id.min_stock_threshold:
                sev = 'critical' if line.product_id.total_stock <= 0 else 'warning'
                self.env['stocksense.inventory.alert'].sudo().create({
                    'product_id': line.product_id.id,
                    'warehouse_id': self.warehouse_id.id,
                    'current_quantity': line.product_id.total_stock,
                    'threshold': line.product_id.min_stock_threshold,
                    'severity': sev,
                    'alert_type': 'low_stock',
                    'detection_mechanism': 'threshold_breach',
                    'reason': f"Stock depleted to {line.product_id.total_stock:.1f} units after dispatch of {line.quantity_delivered:.1f} units on {self.name} (Minimum Safety: {line.product_id.min_stock_threshold:.1f})."
                })
                # Emit Low Stock Alert to alerts topic
                self.env['stocksense.event.outbox'].sudo().queue_or_publish_event(
                    topic=TOPIC_ALERTS,
                    event_type='LOW_STOCK_DETECTED',
                    payload={
                        'product_id': line.product_id.id,
                        'sku': line.product_id.sku,
                        'current_stock': line.product_id.total_stock,
                        'min_threshold': line.product_id.min_stock_threshold,
                        'severity': sev
                    },
                    partition_key=str(line.product_id.id)
                )

        self.write({'state': 'validated'})
        return True

    def action_cancel(self):
        for deliv in self:
            if deliv.state == 'validated':
                raise UserError(_('Cannot cancel a validated delivery.'))
            deliv.write({'state': 'cancelled'})
        return True


class StocksenseDeliveryLine(models.Model):
    _name = 'stocksense.delivery.line'
    _description = 'StockSense Delivery Line Item'

    delivery_id = fields.Many2one('stocksense.delivery', string='Delivery Order', required=True, ondelete='cascade')
    product_id = fields.Many2one('stocksense.product', string='Product', required=True)
    product_sku = fields.Char(related='product_id.sku', string='SKU', readonly=True)
    uom_name = fields.Char(related='product_id.uom_name', string='UoM', readonly=True)
    quantity_requested = fields.Float(string='Ordered Qty', default=1.0, required=True)
    quantity_delivered = fields.Float(string='Delivered Qty', default=1.0, required=True)
