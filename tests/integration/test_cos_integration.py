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
async def test_setup_and_deploy(base, channel, lxd_ctl, k8s_ctl, lxd_model, k8s_model):
    """Setup models and then deploy Hardware Observer and COS."""
    await _deploy_cos(channel, k8s_ctl, k8s_model)

    await _deploy_hardware_observer(base, channel, lxd_model)

    await _add_cross_controller_relations(k8s_ctl, lxd_ctl, k8s_model, lxd_model)

    # This verifies that the cross-controller relation with COS is successful
    assert lxd_model.applications["grafana-agent"].status == "active"


async def test_alerts(ops_test: OpsTest, lxd_model, k8s_model):
    """Verify that the required alerts are fired."""
    await _disable_hardware_exporter(ops_test, lxd_model)
    await _export_mock_metrics(lxd_model)

    # Run juju action to get the ip address that traefik is configured to serve on
    returncode, stdout, stderr = await ops_test.run(
        "juju",
        "run",
        "--format",
        "json",
        "traefik/0",
        "show-proxied-endpoints",
    )
    json_data = json.loads(stdout)
    proxied_endpoints = json.loads(json_data["traefik/0"]["results"]["proxied-endpoints"])
    prometheus_url = proxied_endpoints["prometheus/0"]["url"]
    prometheus_alerts_endpoint = f"{prometheus_url}/api/v1/alerts"
    prometheus_metrics_endpoint = f"{prometheus_url}/metrics"

    # Check relation status
    relation_status = await ops_test.run("juju", "status", "--relations")
    logger.info(f"Relation status: {relation_status}")

    # Check grafana-agent configuration and status
    grafana_agent = lxd_model.applications.get("grafana-agent")
    grafana_agent_unit = grafana_agent.units[0]

    # Check grafana-agent unit data
    ga_unit_data = await ops_test.run("juju", "show-unit", "grafana-agent/0", "--format", "yaml")
    logger.info(f"Grafana-agent unit data: {ga_unit_data}")

    # Check hardware-observer unit data
    ho_unit_data = await ops_test.run("juju", "show-unit", "hardware-observer/0", "--format", "yaml")
    logger.info(f"Hardware-observer unit data: {ho_unit_data}")

    # Check if grafana-agent config exists and what it contains
    config_check = await grafana_agent_unit.run("find /var/lib/juju -name '*prometheus*' -type f")

    # If config exists, show its content
    if config_check.results.get('return-code') == 0:
        logger.info(f"Grafana-agent config files: {config_check.results}")
        config_content = await grafana_agent_unit.run("cat /var/lib/juju -name '*prometheus*' -type f")
        logger.info(f"Grafana-agent prometheus config: {config_content.results}")

    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(45), wait=wait_fixed(20)):
            with attempt:
                # Check what targets Prometheus is actually scraping
                try:
                    targets_response = subprocess.check_output(
                        ["curl", f"{prometheus_url}/api/v1/targets"]
                    )
                    logger.info(f"Prometheus targets: {targets_response}")

                    # Check if hardware-observer target is being scraped
                    targets_data = json.loads(targets_response)["data"]["activeTargets"]
                    hardware_targets = [target for target in targets_data
                                       if "hardware-observer" in str(target) or "10200" in str(target)]
                    logger.info(f"Hardware-observer targets: {hardware_targets}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to fetch targets data from Prometheus: {e}")
                except Exception as e:
                    logger.error(f"Error processing targets data: {e}")

                try:
                    metrics_response = subprocess.check_output(
                        ["curl", prometheus_metrics_endpoint]
                    )
                except subprocess.CalledProcessError:
                    logger.error("Failed to fetch metrics data from Prometheus")
                    raise
                assert "ipmi_dcmi" in str(
                    metrics_response
                ), "Not able to get mock metrics from prometheus"
    except RetryError:
        pytest.fail("Expected metrics not found in Prometheus.")

    cmd = ["curl", prometheus_alerts_endpoint]

    # Sometimes alerts take some time to show after the metrics are exposed on the host.
    # Additionally, some alerts longer duration like 5m, and they take some time to
    # transition to `firing` state.
    # So retrying for upto 15 minutes.
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(45), wait=wait_fixed(20)):
            with attempt:
                # Check what targets Prometheus is actually scraping
                try:
                    targets_response = subprocess.check_output(
                        ["curl", f"{prometheus_url}/api/v1/targets"]
                    )
                    logger.info(f"Prometheus targets: {targets_response}")

                    # Check if hardware-observer target is being scraped
                    targets_data = json.loads(targets_response)["data"]["activeTargets"]
                    hardware_targets = [target for target in targets_data
                                       if "hardware-observer" in str(target) or "10200" in str(target)]
                    logger.info(f"Hardware-observer targets: {hardware_targets}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to fetch targets data from Prometheus: {e}")
                except Exception as e:
                    logger.error(f"Error processing targets data: {e}")

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
                        expected_alert.is_same_alert(received_alert)
                        for received_alert in received_alerts
                    ), f"Expected alert {expected_alert} not found, received_alerts: {alerts}"

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
        "--hidden-import=mock_data",
        str(Path(__file__).parent.resolve() / "export_mock_metrics.py"),
    ]
    try:
        subprocess.run(bundle_cmd)
    except subprocess.CalledProcessError:
        logger.error("Failed to bundle export_mock_metrics")
        raise

    # Verify the bundle was created successfully
    if not Path("./dist/export_mock_metrics").exists():
        logger.error("PyInstaller failed to create the executable")
        raise FileNotFoundError("Mock metrics executable not found")

    # Log bundle creation success
    logger.info(f"PyInstaller bundle created successfully at: {Path('./dist/export_mock_metrics').resolve()}")

    # scp the executable to hardware-observer unit
    await hardware_observer_unit.scp_to("./dist/export_mock_metrics", "/home/ubuntu")

    # Verify the executable was copied successfully and check permissions
    check_file_cmd = "ls -la /home/ubuntu/export_mock_metrics"
    file_check_action = await hardware_observer_unit.run(check_file_cmd)
    await file_check_action.wait()
    logger.info(f"Mock executable file check: {file_check_action.results}")

    # Run the executable with explicit logging to see startup issues
    run_export_mock_metrics_cmd = "/home/ubuntu/export_mock_metrics > /tmp/mock_server.log 2>&1 &"
    await hardware_observer_unit.run(run_export_mock_metrics_cmd)

    # Wait a moment and check the log
    await asyncio.sleep(5)
    log_cmd = "cat /tmp/mock_server.log || echo 'No log file'"
    log_action = await hardware_observer_unit.run(log_cmd)
    await log_action.wait()
    logger.info(f"Mock server startup log: {log_action.results}")

    # Check if the mock server process is running
    check_process_cmd = "ps aux | grep export_mock_metrics"
    process_check_action = await hardware_observer_unit.run(check_process_cmd)
    await process_check_action.wait()
    logger.info(f"Mock server process check: {process_check_action.results}")

    # Check if port 10200 is open and listening
    check_port_cmd = "netstat -tulpn | grep :10200 || ss -tulpn | grep :10200"
    port_check_action = await hardware_observer_unit.run(check_port_cmd)
    await port_check_action.wait()
    logger.info(f"Port 10200 status: {port_check_action.results}")

    # Test if the mock server is serving metrics locally
    test_local_metrics_cmd = "curl -s http://localhost:10200/metrics || echo 'Mock server not responding'"
    local_test_action = await hardware_observer_unit.run(test_local_metrics_cmd)
    await local_test_action.wait()
    logger.info(f"Local mock metrics test: {local_test_action.results}")


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


async def _deploy_hardware_observer(base, channel, model):
    """Deploy Hardware Observer and Grafana Agent on the existing lxd cloud."""
    base_series_mapping = {
        "ubuntu@20.04": "focal",
        "ubuntu@22.04": "jammy",
        "ubuntu@24.04": "noble",
    }
    await asyncio.gather(
        # Principal Ubuntu
        model.deploy(
            "ubuntu",
            num_units=1,
            base=base,
            channel=channel,
            series=base_series_mapping[base],
        ),
        # Hardware Observer
        model.deploy(
            "hardware-observer",
            base=base,
            num_units=0,
            channel=channel,
            series=base_series_mapping[base],
        ),
        # Grafana Agent
        model.deploy(
            "grafana-agent",
            num_units=0,
            base=base,
            channel="1/stable",
            series=base_series_mapping[base],
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
        await lxd_model.add_relation("grafana-agent", saas)

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
