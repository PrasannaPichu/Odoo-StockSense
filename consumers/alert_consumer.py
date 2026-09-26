# -*- coding: utf-8 -*-
"""
StockSense Independent Kafka Alert Consumer
Listens on operational inventory events and alerts topics to monitor critical threshold breaches and anomaly escalations.
"""

import os
import json
import logging
from kafka import KafkaConsumer

_logger = logging.getLogger("stocksense.alert_consumer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TOPIC_ALERTS = "stocksense.inventory.alerts"
TOPIC_EVENTS = "stocksense.inventory.events"

def start_alert_consumer():
    broker = os.environ.get("KAFKA_BROKER", "localhost:9092")
    _logger.info("Initializing StockSense Alert Consumer connecting to %s...", broker)

    try:
        consumer = KafkaConsumer(
            TOPIC_ALERTS,
            TOPIC_EVENTS,
            bootstrap_servers=[broker],
            group_id="stocksense-alerts-group",
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode('utf-8')),
            enable_auto_commit=True
        )
        _logger.info("Alert Consumer subscribed to topics: %s, %s", TOPIC_ALERTS, TOPIC_EVENTS)
    except Exception as e:
        _logger.error("Failed to connect Alert Consumer to Kafka: %s", e)
        return

    for message in consumer:
        try:
            event = message.value
            event_type = event.get('event_type')
            payload = event.get('payload', {})

            if event_type == 'LOW_STOCK_DETECTED':
                sku = payload.get('sku')
                curr = payload.get('current_stock')
                min_th = payload.get('min_threshold')
                sev = payload.get('severity', 'warning').upper()
                _logger.warning("🚨 [ALERT STREAM] %s ALERT: Product %s is below threshold! (Current: %s, Min: %s)", sev, sku, curr, min_th)

            elif event_type == 'DELIVERY_VALIDATED':
                bal = payload.get('balance_after')
                sku = payload.get('product_sku')
                if bal is not None and bal <= 0:
                    _logger.critical("🚨 [CRITICAL DEPLETION] Product %s is completely OUT OF STOCK after dispatch!", sku)

        except Exception as err:
            _logger.error("Error in Alert Consumer: %s", err)

if __name__ == "__main__":
    start_alert_consumer()
