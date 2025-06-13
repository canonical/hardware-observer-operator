"""Helper functions to run functional tests for hardware-observer."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from async_lru import alru_cache

RESOURCES_DIR = Path("./resources/")


@dataclass
class Metric:
    """Class for metric data."""

    name: str
    labels: Optional[str]
    value: float


@dataclass
class Resource:
    """Class for resource data.

    resource_name: Name of juju resource for charm
    file_name: file name for resource
    collector_name: Associated collector name for resource
    bin_name: Name of the binary after installing resource
    file_path: Path to resource file to be attached (None by default)
    """

    resource_name: str
    file_name: str
    collector_name: str
    bin_name: str
    file_path: Optional[str] = None


class MetricsFetchError(Exception):
    """Raise if something goes wrong when fetching metrics from endpoint."""

    pass


class HardwareExporterConfigError(Exception):
    """Raise if something goes wrong when getting hardware-exporter config."""

    pass


class SnapConfigError(Exception):
    """Raise if something goes wrong when getting snap config."""

    pass


async def run_command_on_unit(ops_test, unit_name: str, command: str) -> dict:
    """Run command on unit and return results."""
    complete_command = ["exec", "--unit", unit_name, "--", *command.split()]
    return_code, stdout, _ = await ops_test.juju(*complete_command)
    results = {
        "return-code": return_code,
        "stdout": stdout,
    }
    return results


async def get_hardware_exporter_config(ops_test, unit_name) -> dict:
    """Return hardware-exporter config from endpoint on unit."""
    command = "cat /etc/hardware-exporter-config.yaml"
    results = await run_command_on_unit(ops_test, unit_name, command)
    if results.get("return-code") > 0:
        raise HardwareExporterConfigError
    return yaml.safe_load(results.get("stdout"))


async def get_generic_exporter_metrics(
    ops_test, unit_name: str, port: int, metric_name: str
) -> Optional[list[Metric]]:
    """Return parsed prometheus metric output from Smartctl Exporter on unit.

    Raises MetricsFetchError if command to fetch metrics didn't execute successfully.
    """
    command = f"curl -s localhost:{port}/metrics"
    results = await run_command_on_unit(ops_test, unit_name, command)
    if results.get("return-code") > 0:
        raise MetricsFetchError
    parsed_metrics = parse_generic_exporter_metrics(results.get("stdout").strip(), metric_name)
    return parsed_metrics


@alru_cache
async def get_hardware_exporter_metrics(
    ops_test, unit_name: str
) -> Optional[dict[str, list[Metric]]]:
    """Return parsed prometheus metric output from Hardware Exporter on unit.

    Raises MetricsFetchError if command to fetch metrics didn't execute successfully.
    """
    command = "curl -s localhost:10200"  # curl at default port (see config.yaml)
    results = await run_command_on_unit(ops_test, unit_name, command)
    if results.get("return-code") > 0:
        raise MetricsFetchError
    parsed_metrics = parse_hardware_exporter_metrics(results.get("stdout").strip())
    return parsed_metrics


async def get_snap_config(ops_test, unit_name: str, snap_name: str) -> dict:
    """Return snap config from unit."""
    command = f"snap get {snap_name} -d"
    results = await run_command_on_unit(ops_test, unit_name, command)
    if results.get("return-code") > 0:
        raise SnapConfigError
    return json.loads(results.get("stdout"))


async def assert_snap_installed(ops_test, unit_name: str, snap_name: str) -> bool:
    """Assert whether snap is installed on the model."""
    cmd = f"snap list {snap_name}"
    results = await run_command_on_unit(ops_test, unit_name, cmd)
    if results.get("return-code") > 0 or snap_name not in results.get("stdout"):
        return False
    return True


def assert_metrics(metrics: list[Metric], expected_metric_values_map: dict[str, float]) -> bool:
    """Assert whether values in obtained list of metrics for a collector are as expected.

    Returns False if all expected metrics are not found in the list of provided metrics.
    Otherwise returns True.
    """
    seen_metrics = 0
    for metric in metrics:
        if metric.name in expected_metric_values_map:
            assert metric.value == expected_metric_values_map.get(
                metric.name
            ), f"{metric.name} value is incorrect"
            seen_metrics += 1

    return False if seen_metrics != len(expected_metric_values_map) else True


def _parse_single_metric(metric: str) -> Optional[Metric]:
    """Return a Metric object parsed from a single metric string."""
    # ignore blank lines or comments
    if not metric or metric.startswith("#"):
        return None

    # The regex pattern below uses named capturing groups to extract aspects of the metric.
    # (?P<name>[^\s{]+) captures the metric name and matches one or more chars that are not
    # whitespace or opening curly brace '{'

    # (?:{(?P<label>[^}]*)})? handles optional labels It uses a non-capturing group (?:...)
    # to make the entire portion optional. Inside this group:
    #   {               : Matches an opening curly brace.
    #   (?P<label>[^}]*): Another named capturing group (label) that matches zero or more
    #                     characters that are not a closing curly brace ([^}]*).
    #   }               : Matches a closing curly brace.

    # (?P<value>\d+\.\d+|\d+): This part captures the numeric value.
    # It uses a named capturing group (value) and matches either:
    #   \d+\.\d+  : For obtaining floating point values containing a dot.
    #   |\d+      : OR, one or more digits for integer values.

    pattern = re.compile(r"(?P<name>[^\s{]+)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\d+\.\d+|\d+)")
    match = pattern.match(metric)

    if match:
        name = match.group("name")
        labels = match.group("labels") or None
        value = float(match.group("value"))
        return Metric(name=name, labels=labels, value=value)
    else:
        return None


def parse_generic_exporter_metrics(metrics_input: str, metric_name: str) -> list[Metric]:
    """Parse raw metrics and return a list of parsed Metric Objects.

    For example, parsing this metrics_input for metric_name "smartctl",
        # HELP smartctl_device_smart_status General smart status
        # TYPE smartctl_device_smart_status gauge
        smartctl_device_smart_status{device="nvme0"} 1

        # HELP smartctl_device_power_cycle_count Device power cycle count
        # TYPE smartctl_device_power_cycle_count counter
        smartctl_device_power_cycle_count{device="nvme0"} 495

    would return,
        [
            Metric(name='smartctl_device_smart_status', labels='device="nvme0"', value=1.0),
            Metric(name='smartctl_device_power_cycle_count', labels='device="nvme0"', value=495.0)
        ]
    """
    parsed_metrics = []
    for line in metrics_input.split("\n"):
        metric = _parse_single_metric(line)
        if not metric:
            continue

        name = metric.name
        if name.startswith(metric_name):
            parsed_metrics.append(metric)
    return parsed_metrics


def parse_hardware_exporter_metrics(metrics_input: str) -> dict[str, list[Metric]]:
    """Parse raw metrics and return dictionary of parsed Metric objects for each collector.

    For example, parsing this metrics_input,
        # HELP ipmi_temperature_celsius Temperature measure from temperature sensors
        # TYPE ipmi_temperature_celsius gauge
        ipmi_temperature_celsius{name="Exhaust Temp",state="Nominal",unit="C"} 52.0

        # HELP ipmi_power_watts Power measure from power sensors
        # TYPE ipmi_power_watts gauge
        ipmi_power_watts{name="Sys Fan Pwr",state="Nominal",unit="W"} 20.0

        # HELP megaraid_virtual_drives Number of virtual drives
        # TYPE megaraid_virtual_drives gauge
        megaraid_virtual_drives{controller_id="0"} 1.0

        # HELP redfish_call_success Indicates if call to the redfish API succeeded or not.
        # TYPE redfish_call_success gauge
        redfish_call_success 0.0

    would return,
        {
          "ipmi_sensors": [
                            Metric(name='ipmi_temperature_celsius',
                            labels='name="Exhaust Temp",state="Nominal",unit="C"',
                            value=52.0), Metric(name='ipmi_power_watts',
                            labels='name="Sys Fan Pwr",state="Nominal",unit="W"',
                            value=20.0)
                          ],
          "mega_raid":    [
                            Metric(name='megaraid_virtual_drives',
                            labels='controller_id="0"',
                            value=1.0)
                          ],
          "redfish":      [Metric(name='redfish_call_success', labels=None, value=0.0)],
        }
    """
    parsed_metrics = defaultdict(list)

    for line in metrics_input.split("\n"):
        metric = _parse_single_metric(line)
        if not metric:
            continue

        name = metric.name
        if name.startswith("redfish"):
            parsed_metrics["redfish"].append(metric)
        elif name.startswith("ipmi_dcmi"):
            parsed_metrics["ipmi_dcmi"].append(metric)
        elif name.startswith("ipmi_sel"):
            parsed_metrics["ipmi_sel"].append(metric)
        elif name.startswith("ipmi"):
            parsed_metrics["ipmi_sensor"].append(metric)
        elif name.startswith("poweredgeraid") or name.startswith("perccli"):
            parsed_metrics["poweredge_raid"].append(metric)
        elif name.startswith("megaraid") or name.startswith("storcli"):
            parsed_metrics["mega_raid"].append(metric)
        elif name.startswith("ssacli"):
            parsed_metrics["hpe_ssa"].append(metric)
    return parsed_metrics
