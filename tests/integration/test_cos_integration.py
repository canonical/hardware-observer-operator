#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import pytest
from mock_data import EXPECTED_ALERTS, SAMPLE_METRICS
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


async def test_hardware_observer_metrics_in_prometheus(ops_test: OpsTest, lxd_model, k8s_model):
    """Verify metrics from HWO are available in Prometheus via COS."""
    # Get Prometheus URL
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
    prometheus_metrics_endpoint = f"{prometheus_url}/metrics"

    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(30), wait=wait_fixed(20)):
            with attempt:
                # Check if hardware observer metrics are available in Prometheus
                try:
                    metrics_response = subprocess.check_output(
                        ["curl", "-s", prometheus_metrics_endpoint]
                    )
                    metrics_str = metrics_response.decode("utf-8")

                    # Find all metrics from HWO
                    metric_lines = [
                        line for line in metrics_str.split("\n") if "hardware_observer" in line
                    ]

                    if metric_lines:
                        logger.info(f"Found {len(metric_lines)} metrics from Hardware Observer:")
                        num_show = min(5, len(metric_lines))
                        for metric_line in metric_lines[:num_show]:
                            logger.info(f"  {metric_line}")
                        if len(metric_lines) > num_show:
                            logger.info(f"  ... and {len(metric_lines) - num_show} more metrics")
                        logger.info("COS can read from Hardware Observer!")
                        break
                    else:
                        raise AssertionError("No HWO metrics found in Prometheus")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to fetch HWO metrics from Prometheus: {e}")
                    raise
                except AssertionError:
                    raise

    except RetryError:
        # Get hardware observer unit
        hardware_observer = lxd_model.applications.get("hardware-observer")
        hardware_observer_unit = hardware_observer.units[0]

        # Show hardware-exporter service status
        service_status_cmd = "sudo systemctl is-active hardware-exporter.service"
        service_status_action = await hardware_observer_unit.run(service_status_cmd)
        await service_status_action.wait()
        logger.debug(f"Hardware exporter service status: {service_status_action.results}")

        # Show metrics are available on the correct port
        test_local_metrics_cmd = "curl -s http://localhost:10200/metrics | head -20"
        local_test_action = await hardware_observer_unit.run(test_local_metrics_cmd)
        await local_test_action.wait()
        logger.debug(f"Local hardware observer metrics sample: {local_test_action.results}")

        pytest.fail(
            "No Hardware Observer metrics found in Prometheus after retries. "
            "Hardware Observer may not be connected to COS properly."
        )


async def test_alerts(ops_test: OpsTest, lxd_model, k8s_model):
    """Verify that the required alerts are fired."""
    await _disable_hardware_exporter(ops_test, lxd_model)
    await _export_mock_metrics(lxd_model)
    await _restart_grafana_agent(ops_test, lxd_model)

    # Check if hardware-exporter service is actually stopped
    hardware_observer = lxd_model.applications.get("hardware-observer")
    hardware_observer_unit = hardware_observer.units[0]
    service_check_cmd = (
        "sudo systemctl is-active hardware-exporter.service || echo 'Service stopped'"
    )
    service_action = await hardware_observer_unit.run(service_check_cmd)
    await service_action.wait()
    logger.info(f"Hardware-exporter service status: {service_action.results}")

    # Check if Grafana Agent is running
    agent_check_cmd = "sudo systemctl is-active snap.grafana-agent.grafana-agent.service"
    agent_action = await hardware_observer_unit.run(agent_check_cmd)
    await agent_action.wait()
    logger.info(f"Grafana Agent service status: {agent_action.results}")

    # Check mock server is actually serving mock metrics
    test_mock_cmd = "curl -s http://localhost:10200/metrics | grep -E '(ipmi_dcmi_command_success|ipmi_temperature_celsius)'"
    mock_test_action = await hardware_observer_unit.run(test_mock_cmd)
    await mock_test_action.wait()
    logger.info("Mock metrics from localhost:10200:")
    logger.info(f"{mock_test_action.results}")

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
    prometheus_query_url = f"{prometheus_url}/api/v1/query"
    prometheus_alerts_endpoint = f"{prometheus_url}/api/v1/alerts"

    # Metrics need to validate against
    required_metrics = {
        metric["name"]: metric["value"]
        for metric in SAMPLE_METRICS
        if metric["name"] in ["ipmi_dcmi_command_success", "ipmi_temperature_celsius"]
    }

    logger.info("=== Verifying mock metrics in Prometheus ===")

    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(60), wait=wait_fixed(30)):
            with attempt:
                all_metrics_found = True

                for metric_name, expected_value in required_metrics.items():
                    logger.info(
                        f"Attempt {attempt.retry_state.attempt_number}/60: Checking for `{metric_name}`={expected_value}"
                    )

                    try:
                        cmd = ["curl", "-s", f"{prometheus_query_url}?query={metric_name}"]
                        response = subprocess.check_output(cmd)
                        result = json.loads(response.decode("utf-8"))

                        if not result.get("data", {}).get("result"):
                            logger.info(f"`{metric_name}` not found")
                            all_metrics_found = False
                        else:
                            found_value = float(result["data"]["result"][0]["value"][1])
                            if found_value != expected_value:
                                logger.info(
                                    f"`{metric_name}` found but wrong value: {found_value} (expected {expected_value})"
                                )
                                all_metrics_found = False
                            else:
                                logger.info(
                                    f"`{metric_name}` found with correct value: {found_value}"
                                )

                    except (
                        subprocess.CalledProcessError,
                        json.JSONDecodeError,
                        KeyError,
                        IndexError,
                    ) as e:
                        logger.info(f"  Error checking `{metric_name}`: {e}")
                        all_metrics_found = False

                if not all_metrics_found:
                    raise AssertionError("Required metrics not found with expected values")

                logger.info("All required metrics found with expected values!")
                break

    except RetryError:
        metric_descriptions = [f"`{name}`={value}" for name, value in required_metrics.items()]
        pytest.fail(
            f"Required metrics ({', '.join(metric_descriptions)}) not found in Prometheus after retries."
            ""
        )

    logger.info("=== Verifying alerts are firing ===")
    cmd = ["curl", prometheus_alerts_endpoint]

    # Sometimes alerts take some time to show after the metrics are exposed on the host.
    # Additionally, some alerts longer duration like 5m, and they take some time to
    # transition to `firing` state.
    # So retrying for up to 20 minutes.
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(60), wait=wait_fixed(30)):
            with attempt:
                logger.info(
                    f"Attempt {attempt.retry_state.attempt_number}/20: Checking for firing alerts"
                )
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

                missing_alerts = []
                for expected_alert in expected_alerts:
                    if not any(
                        expected_alert.is_same_alert(received_alert)
                        for received_alert in received_alerts
                    ):
                        missing_alerts.append(expected_alert)

                if missing_alerts:
                    logger.info(f"Missing alerts: {missing_alerts}")
                    raise AssertionError(f"Expected alerts not found: {missing_alerts}")

                logger.info("All expected alerts are firing!")
                break

    except RetryError:
        pytest.fail("Expected alerts not found in COS after metrics were confirmed in Prometheus.")


async def _restart_grafana_agent(ops_test: OpsTest, lxd_model):
    """Restart Grafana Agent to ensure it picks up new metrics."""
    restart_cmd = "sudo systemctl restart snap.grafana-agent.grafana-agent.service"

    hardware_observer = lxd_model.applications.get("hardware-observer")
    hardware_observer_unit = hardware_observer.units[0]

    restart_action = await hardware_observer_unit.run(restart_cmd)
    await restart_action.wait()

    logger.info(f"Grafana Agent restart status: {restart_action.results}")


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

    scripts_dir = Path(__file__).parent.resolve()
    export_script = scripts_dir / "export_mock_metrics.py"
    mock_data_script = scripts_dir / "mock_data.py"

    # Verify scripts exist locally
    if not export_script.exists():
        raise FileNotFoundError(f"Export script not found: {export_script}")
    if not mock_data_script.exists():
        raise FileNotFoundError(f"Mock data script not found: {mock_data_script}")

    # Copy Python scripts to hardware-observer unit
    await hardware_observer_unit.scp_to(str(export_script), "/home/ubuntu/")
    await hardware_observer_unit.scp_to(str(mock_data_script), "/home/ubuntu/")

    # Verify the scripts were copied successfully
    check_files_cmd = "ls -la /home/ubuntu/export_mock_metrics.py /home/ubuntu/mock_data.py"
    file_check_action = await hardware_observer_unit.run(check_files_cmd)
    await file_check_action.wait()
    logger.info(f"Mock scripts file check: {file_check_action.results}")

    # Setup Python environment on the remote unit
    await _setup_python_environment(hardware_observer_unit)

    # Run the export mock metrics script as subprocess
    run_export_mock_metrics_cmd = """
cd /home/ubuntu
python3 -c "
import subprocess
import sys
import time

try:
    proc = subprocess.Popen(
        [sys.executable, 'export_mock_metrics.py'],
        stdout=open('/tmp/mock_server.log', 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    
    with open('/tmp/mock_server.pid', 'w') as f:
        f.write(str(proc.pid))
    
    print(f'Started mock server PID: {proc.pid}')
    
    time.sleep(5)
    if proc.poll() is not None:
        print(f'ERROR: Process exited with code {proc.poll()}')
        sys.exit(1)
        
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
"
"""
    mock_start_action = await hardware_observer_unit.run(run_export_mock_metrics_cmd)
    await mock_start_action.wait()
    logger.info(f"Mock server start result: {mock_start_action.results}")

    # Wait a moment and check the log
    await asyncio.sleep(5)
    log_cmd = "cat /tmp/mock_server.log || echo 'No log file'"
    log_action = await hardware_observer_unit.run(log_cmd)
    await log_action.wait()
    logger.info(f"Mock server startup log: {log_action.results}")

    # Check if the mock server process is running
    check_process_cmd = "ps aux | grep 'python3 export_mock_metrics.py' | grep -v grep"
    process_check_action = await hardware_observer_unit.run(check_process_cmd)
    await process_check_action.wait()
    logger.info(f"Mock server process check: {process_check_action.results}")

    # Check if port 10200 is open and listening
    check_port_cmd = "ss -tulpn | grep :10200"
    port_check_action = await hardware_observer_unit.run(check_port_cmd)
    await port_check_action.wait()
    logger.info(f"Port 10200 status: {port_check_action.results}")

    # Test if the mock server is serving metrics locally
    test_local_metrics_cmd = (
        "curl -s http://localhost:10200/metrics || echo 'Mock server not responding'"
    )
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


async def _setup_python_environment(unit):
    """Set up Python environment on the input unit."""
    logger.info("Setting up Python environment on input unit")

    # Install pip
    install_pip_cmd = "sudo apt update && sudo apt install -y python3-pip"
    pip_action = await unit.run(install_pip_cmd)
    await pip_action.wait()
    logger.info(f"Pip installation: {pip_action.results}")

    # Install prometheus_client
    install_deps_cmd = "python3 -m pip install prometheus_client"
    deps_action = await unit.run(install_deps_cmd)
    await deps_action.wait()
    logger.info(f"Dependencies installation: {deps_action.results}")
