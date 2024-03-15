#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# This file is supposed to run on the hardware observer unit.

import time

from mock_data import SAMPLE_METRICS
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily

from config import EXPORTER_DEFAULT_PORT


class SyntheticCollector:
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
    start_http_server(int(EXPORTER_DEFAULT_PORT))
    REGISTRY.register(SyntheticCollector())

    while True:
        time.sleep(10)  # Keep the server running
