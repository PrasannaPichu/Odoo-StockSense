# -*- coding: utf-8 -*-
"""
StockSense Kafka Event Streaming Producer
Handles publishing operational inventory events to Apache Kafka with partition key routing and graceful outbox fallback.
"""

import os
import json
import uuid
import datetime
import logging

_logger = logging.getLogger(__name__)

# Kafka Topics
TOPIC_EVENTS = "stocksense.inventory.events"
TOPIC_ALERTS = "stocksense.inventory.alerts"
TOPIC_ANALYTICS = "stocksense.inventory.analytics"
TOPIC_AUDIT = "stocksense.inventory.audit"

_PRODUCER_INSTANCE = None


def get_kafka_producer():
    """Lazily initialize and return the Kafka producer client."""
    global _PRODUCER_INSTANCE
    if _PRODUCER_INSTANCE is not None:
        return _PRODUCER_INSTANCE

    broker = os.environ.get("KAFKA_BROKER", "localhost:9092")
    try:
        from kafka import KafkaProducer
        _PRODUCER_INSTANCE = KafkaProducer(
            bootstrap_servers=[broker],
            value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
            key_serializer=lambda k: str(k).encode('utf-8') if k is not None else None,
            acks='all',
            retries=3,
            request_timeout_ms=5000,
        )
        _logger.info("Kafka Producer successfully initialized connected to %s", broker)
    except Exception as e:
        _logger.warning("Kafka Producer unavailable on %s: %s (Will use PostgreSQL Outbox fallback)", broker, e)
        _PRODUCER_INSTANCE = None

    return _PRODUCER_INSTANCE


def publish_event(topic, event_type, payload, partition_key=None, metadata=None):
    """
    Publish an event to a Kafka topic.
    Returns:
        dict: {
            'success': bool,
            'event_id': str,
            'topic': str,
            'partition_key': str,
            'timestamp': str,
            'error': str or None
        }
    """
    event_id = f"evt_{uuid.uuid4()}"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "version": "1.0",
        "timestamp": timestamp,
        "producer": "odoo_stocksense",
        "payload": payload,
        "metadata": metadata or {}
    }

    producer = get_kafka_producer()
    if producer is None:
        return {
            'success': False,
            'event_id': event_id,
            'topic': topic,
            'partition_key': str(partition_key) if partition_key else None,
            'timestamp': timestamp,
            'envelope': envelope,
            'error': "Kafka producer not connected"
        }

    try:
        key = str(partition_key) if partition_key is not None else None
        future = producer.send(topic, key=key, value=envelope)
        record_metadata = future.get(timeout=3)
        _logger.debug(
            "Event %s [%s] published to %s (partition=%s, offset=%s)",
            event_id, event_type, topic, record_metadata.partition, record_metadata.offset
        )
        return {
            'success': True,
            'event_id': event_id,
            'topic': topic,
            'partition': record_metadata.partition,
            'offset': record_metadata.offset,
            'timestamp': timestamp,
            'envelope': envelope,
            'error': None
        }
    except Exception as e:
        _logger.error("Failed to publish event %s [%s] to Kafka topic %s: %s", event_id, event_type, topic, e)
        return {
            'success': False,
            'event_id': event_id,
            'topic': topic,
            'partition_key': str(partition_key) if partition_key else None,
            'timestamp': timestamp,
            'envelope': envelope,
            'error': str(e)
        }
