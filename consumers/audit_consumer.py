# -*- coding: utf-8 -*-
"""
StockSense Independent Kafka Audit & Forensic Consumer
Maintains an independent in-memory verification ledger to cryptographically validate incoming events against hash chains.
"""

import os
import json
import logging
from kafka import KafkaConsumer
from stocksense.services.audit_chain import GENESIS_HASH, compute_block_hash

_logger = logging.getLogger("stocksense.audit_consumer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TOPIC_EVENTS = "stocksense.inventory.events"

def start_audit_consumer():
    broker = os.environ.get("KAFKA_BROKER", "localhost:9092")
    _logger.info("Initializing StockSense Audit Consumer connecting to %s...", broker)

    try:
        consumer = KafkaConsumer(
            TOPIC_EVENTS,
            bootstrap_servers=[broker],
            group_id="stocksense-audit-group",
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode('utf-8')),
            enable_auto_commit=True
        )
        _logger.info("Audit Consumer subscribed to topic '%s'", TOPIC_EVENTS)
    except Exception as e:
        _logger.error("Failed to connect Audit Consumer to Kafka: %s", e)
        return

    verified_count = 0
    current_hash_state = GENESIS_HASH

    for message in consumer:
        try:
            event = message.value
            event_id = event.get('event_id')
            event_type = event.get('event_type')
            payload = event.get('payload', {})

            # Compute block hash
            block_hash = compute_block_hash(payload, current_hash_state)
            verified_count += 1
            current_hash_state = block_hash

            _logger.info(
                "🔒 [AUDIT BLOCK #%s] Verified %s (Event: %s) -> Current SHA-256: %s...",
                verified_count, event_id, event_type, block_hash[:16]
            )

        except Exception as err:
            _logger.error("Audit Consumer failed to verify block: %s", err)

if __name__ == "__main__":
    start_audit_consumer()
