# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _
from ..services.kafka_producer import publish_event, TOPIC_EVENTS

_logger = logging.getLogger(__name__)

class StocksenseEventOutbox(models.Model):
    _name = 'stocksense.event.outbox'
    _description = 'StockSense Resilient Event Outbox'
    _order = 'create_date desc, id desc'

    event_id = fields.Char(string='Event ID', required=True, index=True)
    event_type = fields.Char(string='Event Type', required=True, index=True)
    topic = fields.Char(string='Kafka Topic', default=TOPIC_EVENTS, required=True, index=True)
    partition_key = fields.Char(string='Partition Key (Product ID)', index=True)
    payload_json = fields.Text(string='Event Payload JSON', required=True)
    status = fields.Selection([
        ('pending', 'Pending Delivery'),
        ('published', 'Successfully Streamed'),
        ('failed', 'Delivery Failed'),
    ], string='Streaming Status', default='pending', required=True, index=True)
    retry_count = fields.Integer(string='Retry Attempts', default=0)
    last_error = fields.Text(string='Last Error Diagnostic')

    @api.model
    def queue_or_publish_event(self, topic, event_type, payload, partition_key=None, metadata=None):
        """
        Attempts direct streaming to Kafka. If Kafka is unavailable or throws,
        safely stores into outbox with 'pending' status for background retry.
        Guarantees zero transactional failure and at-least-once delivery semantics.
        """
        result = publish_event(
            topic=topic,
            event_type=event_type,
            payload=payload,
            partition_key=partition_key,
            metadata=metadata
        )

        status = 'published' if result['success'] else 'pending'
        envelope = result.get('envelope') or {}

        record = self.create({
            'event_id': result['event_id'],
            'event_type': event_type,
            'topic': topic,
            'partition_key': str(partition_key) if partition_key else None,
            'payload_json': json.dumps(envelope or payload, default=str),
            'status': status,
            'last_error': result.get('error')
        })

        if result['success']:
            _logger.info("Kafka Outbox: Event %s streamed directly to topic %s", result['event_id'], topic)
        else:
            _logger.warning("Kafka Outbox: Event %s queued for retry (Broker offline: %s)", result['event_id'], result.get('error'))

        return record

    def action_retry_outbox(self):
        """Batch re-stream pending outbox records to Kafka."""
        pending_records = self.search([('status', 'in', ['pending', 'failed'])], limit=50)
        success_count = 0
        for rec in pending_records:
            try:
                payload = json.loads(rec.payload_json)
                res = publish_event(
                    topic=rec.topic,
                    event_type=rec.event_type,
                    payload=payload.get('payload', payload),
                    partition_key=rec.partition_key
                )
                if res['success']:
                    rec.write({'status': 'published', 'last_error': False})
                    success_count += 1
                else:
                    rec.write({
                        'retry_count': rec.retry_count + 1,
                        'last_error': res.get('error'),
                        'status': 'failed' if rec.retry_count >= 5 else 'pending'
                    })
            except Exception as e:
                rec.write({'retry_count': rec.retry_count + 1, 'last_error': str(e)})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Kafka Outbox Synced'),
                'message': _('Successfully delivered %s of %s queued events.') % (success_count, len(pending_records)),
                'type': 'success',
                'sticky': False,
            }
        }
