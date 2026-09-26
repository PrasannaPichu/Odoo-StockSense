# -*- coding: utf-8 -*-
"""
StockSense Independent Kafka Analytics Consumer
Processes real-time inventory telemetry to compute consumption velocity, inventory turnover, and rolling aggregations.
"""

import os
import json
import logging
from kafka import KafkaConsumer

_logger = logging.getLogger("stocksense.analytics_consumer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TOPIC_EVENTS = "stocksense.inventory.events"

def start_analytics_consumer():
    broker = os.environ.get("KAFKA_BROKER", "localhost:9092")
    _logger.info("Initializing StockSense Analytics Consumer connecting to %s...", broker)

    try:
        consumer = KafkaConsumer(
            TOPIC_EVENTS,
            bootstrap_servers=[broker],
            group_id="stocksense-analytics-group",
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode('utf-8')),
            enable_auto_commit=True
        )
        _logger.info("Analytics Consumer subscribed to topic '%s'", TOPIC_EVENTS)
    except Exception as e:
        _logger.error("Failed to connect Analytics Consumer to Kafka: %s", e)
        return

    rolling_stats = {
        'total_receipts_qty': 0.0,
        'total_deliveries_qty': 0.0,
        'total_adjustments_qty': 0.0,
        'product_consumption': {}
    }

    for message in consumer:
        try:
            event = message.value
            event_type = event.get('event_type')
            payload = event.get('payload', {})
            sku = payload.get('product_sku', 'UNKNOWN')
            qty = float(payload.get('quantity') or payload.get('quantity_delta') or 0.0)

            if event_type == 'RECEIPT_VALIDATED':
                rolling_stats['total_receipts_qty'] += qty
                _logger.info("[ANALYTICS] Inbound Flow: +%s units for %s (Cumulative Receipts: %s)", qty, sku, rolling_stats['total_receipts_qty'])

            elif event_type == 'DELIVERY_VALIDATED':
                rolling_stats['total_deliveries_qty'] += qty
                rolling_stats['product_consumption'][sku] = rolling_stats['product_consumption'].get(sku, 0.0) + qty
                _logger.info("[ANALYTICS] Outbound Demand: -%s units for %s (Cumulative Outflow: %s)", qty, sku, rolling_stats['total_deliveries_qty'])

            elif event_type == 'STOCK_ADJUSTED':
                delta = float(payload.get('discrepancy_delta', 0.0))
                rolling_stats['total_adjustments_qty'] += delta
                _logger.info("[ANALYTICS] Physical Adjustment Variance: Δ %s for %s", delta, sku)

        except Exception as err:
            _logger.error("Error processing event in Analytics Consumer: %s", err)

if __name__ == "__main__":
    start_analytics_consumer()
