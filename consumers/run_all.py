# -*- coding: utf-8 -*-
"""
StockSense Multi-Consumer Runner
Starts Analytics, Alert, and Audit consumers in coordinated parallel processes.
"""

import time
import logging
from multiprocessing import Process
from analytics_consumer import start_analytics_consumer
from alert_consumer import start_alert_consumer
from audit_consumer import start_audit_consumer

_logger = logging.getLogger("stocksense.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def main():
    _logger.info("Starting all StockSense Kafka Consumer workers...")

    processes = [
        Process(target=start_analytics_consumer, name="AnalyticsConsumer"),
        Process(target=start_alert_consumer, name="AlertConsumer"),
        Process(target=start_audit_consumer, name="AuditConsumer"),
    ]

    for p in processes:
        p.start()
        _logger.info("Launched worker process: %s (PID: %s)", p.name, p.pid)

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        _logger.info("Shutting down consumer workers gracefully...")
        for p in processes:
            p.terminate()

if __name__ == "__main__":
    main()
