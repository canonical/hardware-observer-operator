#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import pytest
from mock_data import EXPECTED_ALERTS
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_fixed
from utils import Alert

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_setup_and_deploy(series, channel, lxd_ctl, k8s_ctl, lxd_model, k8s_model):
    """Setup models and then deploy Hardware Observer and COS."""
    await _deploy_cos(channel, k8s_ctl, k8s_model)

    await _deploy_hardware_observer(series, channel, lxd_model)

    await _add_cross_controller_relations(k8s_ctl, lxd_ctl, k8s_model, lxd_model)

    # This verifies that the cross-controller relation with COS is successful
    assert lxd_model.applications["grafana-agent"].status == "active"


async def test_alerts(ops_test: OpsTest, lxd_model, k8s_model):
    """Verify that the required alerts are fired."""
    await _disable_hardware_exporter(ops_test, lxd_model)
    await _export_mock_metrics(lxd_model)

    model_name = ops_test.model_name

    model_status = await k8s_model.get_status()
    traefik_ip = model_status["applications"]["traefik"].public_address

    prometheus_alerts_endpoint = f"http://{traefik_ip}/{model_name}-prometheus-0/api/v1/alerts"

    cmd = ["curl", prometheus_alerts_endpoint]

    # Sometimes alerts take some time to show after the metrics are exposed on the host.
    # So retrying for upto 5 minutes.
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(15), wait=wait_fixed(20)):
            with attempt:
                try:
                    alerts_response = subprocess.check_output(cmd)
                except subprocess.CalledProcessError:
                    logger.error("Failed to fetch alerts data from COS")
                    raise

                alerts = json.loads(alerts_response)["data"]["alerts"]

                received_alerts = [
                    Alert(
                        state=received_alert["state"],
                        value=float(received_alert["value"]),
                        labels=received_alert["labels"],
                    )
                    for received_alert in alerts
                ]
                expected_alerts = [
                    Alert(
                        state=expected_alert["state"],
                        value=float(expected_alert["value"]),
                        labels=expected_alert["labels"],
                    )
                    for expected_alert in EXPECTED_ALERTS
                ]

                for expected_alert in expected_alerts:
                    assert any(
                        # Comparing using custom __eq__ based only on relevant fields
                        expected_alert == received_alert
                        for received_alert in received_alerts
                    )

    except RetryError:
        pytest.fail("Expected alerts not found in COS.")


async def _disable_hardware_exporter(ops_test: OpsTest, lxd_model):
    """Disable the hardware exporter service."""
    disable_cmd = "sudo systemctl stop hardware-exporter.service"

    hardware_observer = lxd_model.applications.get("hardware-observer")
    hardware_observer_unit = hardware_observer.units[0]

    disable_action = await hardware_observer_unit.run(disable_cmd)
    await disable_action.wait()


async def _export_mock_metrics(lxd_model):
    """Expose the mock metrics for further testing."""
    hardware_observer = lxd_model.applications.get("hardware-observer")
    hardware_observer_unit = hardware_observer.units[0]

    # Create an executable from `export_mock_metrics.py`
    bundle_cmd = [
        "pyinstaller",
        "--onefile",
        str(Path(__file__).parent.resolve() / "export_mock_metrics.py"),
    ]
    try:
        subprocess.run(bundle_cmd)
    except subprocess.CalledProcessError:
        logger.error("Failed to bundle export_mock_metrics")
        raise

    # scp the executable to hardware-observer unit
    await hardware_observer_unit.scp_to("./dist/export_mock_metrics", "/home/ubuntu")

    # Run the executable in the background without waiting.
    run_export_mock_metrics_cmd = "/home/ubuntu/export_mock_metrics"
    await hardware_observer_unit.run(run_export_mock_metrics_cmd)


async def _deploy_cos(channel, ctl, model):
    """Deploy COS on the existing k8s cloud."""
    # Deploying via CLI because of https://github.com/juju/python-libjuju/issues/1032.
    cmd = [
        "juju",
        "deploy",
        "cos-lite",
        "--channel",
        channel,
        "--trust",
        "-m",
        f"{ctl.controller_name}:{model.name}",
        "--overlay",
        str(Path(__file__).parent.resolve() / "offers-overlay.yaml"),
    ]
    subprocess.run(cmd, check=True)


async def _deploy_hardware_observer(series, channel, model):
    """Deploy Hardware Observer and Grafana Agent on the existing lxd cloud."""
    await asyncio.gather(
        # Principal Ubuntu
        model.deploy(
            "ubuntu",
            num_units=1,
            series=series,
            channel=channel,
        ),
        # Hardware Observer
        model.deploy("hardware-observer", series=series, num_units=0, channel=channel),
        # Grafana Agent
        model.deploy(
            "grafana-agent",
            num_units=0,
            series=series,
            channel=channel,
        ),
    )

    await model.add_relation("ubuntu:juju-info", "hardware-observer:general-info")
    await model.add_relation("hardware-observer:cos-agent", "grafana-agent:cos-agent")
    await model.add_relation("ubuntu:juju-info", "grafana-agent:juju-info")

    await model.block_until(lambda: model.applications["hardware-observer"].status == "active")


async def _add_cross_controller_relations(k8s_ctl, lxd_ctl, k8s_model, lxd_model):
    """Add relations between Grafana Agent and COS."""
    cos_saas_names = ["prometheus-receive-remote-write", "loki-logging", "grafana-dashboards"]
    for saas in cos_saas_names:
        # Using juju cli since Model.consume() from libjuju causes error.
        # https://github.com/juju/python-libjuju/issues/1031
        cmd = [
            "juju",
            "consume",
            "--model",
            f"{lxd_ctl.controller_name}:{k8s_model.name}",
            f"{k8s_ctl.controller_name}:admin/{k8s_model.name}.{saas}",
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        await lxd_model.add_relation("grafana-agent", saas),

    # `idle_period` needs to be greater than the scrape interval to make sure metrics ingested.
    await asyncio.gather(
        # First, we wait for the critical phase to pass with raise_on_error=False.
        # (In CI, using github runners, we often see unreproducible hook failures.)
        lxd_model.wait_for_idle(timeout=1800, idle_period=180, raise_on_error=False),
        k8s_model.wait_for_idle(timeout=1800, idle_period=180, raise_on_error=False),
    )

    await asyncio.gather(
        # Then we wait for "active", without raise_on_error=False, so the test fails sooner in case
        # there is a persistent error status.
        lxd_model.wait_for_idle(status="active", timeout=7200, idle_period=180),
        k8s_model.wait_for_idle(status="active", timeout=7200, idle_period=180),
    )
