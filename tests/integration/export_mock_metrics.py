#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# This file is supposed to run on the hardware observer unit.

import logging
import socket
import sys
import time

from mock_data import SAMPLE_METRICS
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)


class SyntheticCollector(Collector):
    """Collector for creating synthetic(mock) metrics."""

    def collect(self):
        for sample_metric in SAMPLE_METRICS:
            metric = GaugeMetricFamily(
                name=sample_metric["name"],
                documentation=sample_metric["documentation"],
                labels=list(sample_metric["labels"].keys()),
            )
            metric.add_metric(  # type: ignore[attr-defined]
                labels=list(sample_metric["labels"].values()), value=sample_metric["value"]
            )
            yield metric


if __name__ == "__main__":
    port = 10200  # Default port for the mock metrics server (see `config.yaml`)

    try:
        start_http_server(port)
        REGISTRY.register(SyntheticCollector())

        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        logger.info(f"Mock metrics server started on {ip_address}:{port}")

        for sample_metric in SAMPLE_METRICS:
            logger.info(
                f"Exposing metric: {sample_metric['name']} with value: {sample_metric['value']} "
                f"and labels: {sample_metric['labels']}"
            )

        while True:
            time.sleep(10)  # Keep the server running

    except Exception as e:
        logger.error(f"Failed to start mock metrics server: {e}")
        sys.exit(1)
