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

    hardware_observer = lxd_model.applications.get("hardware-observer")
    hardware_observer_unit = hardware_observer.units[0]

    try:
        # Debug hardware detection and services before starting
        await _debug_hardware_detection_and_services(hardware_observer_unit)

        # Stop existing hardware-exporter service (may or may not exist)
        await _disable_hardware_exporter(ops_test, lxd_model)

        # Start mock server
        await _export_mock_metrics(lxd_model)

        # Patch Grafana Agent config to scrape the mock server
        await _patch_grafana_agent_for_mock_server(hardware_observer_unit)

        # Restart Grafana Agent to pick up the new config
        await _restart_grafana_agent(ops_test, lxd_model)

        # Verify Grafana Agent is now scraping the mock server
        verify_config_cmd = """
echo "=== Verifying Grafana Agent is configured for mock server ==="
grep -A 10 "hardware-observer_1_default" /etc/grafana-agent.yaml
echo "=== Checking if port 10200 is in config ==="
grep "10200" /etc/grafana-agent.yaml && echo "Port 10200 found in config" || echo "Port 10200 NOT found in config"
"""
        verify_action = await hardware_observer_unit.run(verify_config_cmd)
        await verify_action.wait()
        logger.info(f"Grafana Agent config verification: {verify_action.results}")

    except Exception as e:
        logger.error(f"Error in test setup: {e}")
        # Attempt to restore config even if setup failed
        try:
            await _restore_grafana_agent_config(hardware_observer_unit)
        except:
            pass
        raise

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

    finally:
        # Cleanup: Restore original Grafana Agent configuration
        try:
            await _restore_grafana_agent_config(hardware_observer_unit)
        except Exception as cleanup_error:
            logger.warning(f"Failed to restore Grafana Agent config during cleanup: {cleanup_error}")


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


async def _patch_grafana_agent_for_mock_server(hardware_observer_unit):
    """Patch Grafana Agent configuration to scrape mock server on port 10200."""
    logger.info("Patching Grafana Agent configuration for mock server...")

    patch_config_cmd = """
#!/bin/bash
set -e

CONFIG_FILE="/etc/grafana-agent.yaml"
BACKUP_FILE="/etc/grafana-agent.yaml.backup"

# Create backup
sudo cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "Created backup: $BACKUP_FILE"

# Patch the YAML
echo "Patching Grafana Agent config to point to mock server..."
sudo python3 -c "
import yaml
import sys
import subprocess
import tempfile

CONFIG_FILE = '/etc/grafana-agent.yaml'

# Read the config with proper permissions
try:
    result = subprocess.run(['cat', CONFIG_FILE], capture_output=True, text=True, check=True)
    config = yaml.safe_load(result.stdout)
except Exception as e:
    print(f'ERROR: Failed to read config file: {e}')
    sys.exit(1)

# Find the metrics config
metrics_config = config.get('metrics', {}).get('configs', [])
if not metrics_config:
    print('ERROR: No metrics config found')
    sys.exit(1)

# Find the scrape configs
scrape_configs = metrics_config[0].get('scrape_configs', [])

# Extract juju_model_uuid from existing job
juju_model_uuid = None
for job in scrape_configs:
    if job.get('static_configs'):
        for static_config in job['static_configs']:
            if static_config.get('labels', {}).get('juju_model_uuid'):
                juju_model_uuid = static_config['labels']['juju_model_uuid']
                print(f'Found juju_model_uuid: {juju_model_uuid}')
                break
        if juju_model_uuid:
            break

# If no juju_model_uuid found in jobs, try to find it in other parts of config
if not juju_model_uuid:
    logs_config = config.get('logs', {}).get('configs', [])
    for log_config in logs_config:
        for scrape_config in log_config.get('scrape_configs', []):
            if scrape_config.get('static_configs'):
                for static_config in scrape_config['static_configs']:
                    if static_config.get('labels', {}).get('juju_model_uuid'):
                        juju_model_uuid = static_config['labels']['juju_model_uuid']
                        print(f'Found juju_model_uuid in logs config: {juju_model_uuid}')
                        break
            elif scrape_config.get('journal', {}).get('labels', {}).get('juju_model_uuid'):
                juju_model_uuid = scrape_config['journal']['labels']['juju_model_uuid']
                print(f'Found juju_model_uuid in journal config: {juju_model_uuid}')
                break
        if juju_model_uuid:
            break

if not juju_model_uuid:
    print('WARNING: Could not find juju_model_uuid in config, using placeholder')
    juju_model_uuid = 'unknown-model-uuid'

# Find and patch the hardware-observer job, or create it if missing
job_found = False
for job in scrape_configs:
    if job.get('job_name') == 'hardware-observer_1_default':
        job_found = True
        current_targets = job.get('static_configs', [{}])[0].get('targets', []) if job.get('static_configs') else []
        print(f'Found existing hardware-observer_1_default job with current targets: {current_targets}')

        # Ensure static_configs exists and is properly structured
        if not job.get('static_configs') or len(job['static_configs']) == 0:
            job['static_configs'] = [{}]

        static_config = job['static_configs'][0]

        # Update targets
        static_config['targets'] = ['localhost:10200']

        # Ensure labels exist and update/preserve them
        if 'labels' not in static_config:
            static_config['labels'] = {}

        # Update labels with required values, preserving existing ones
        static_config['labels'].update({
            'juju_application': 'hardware-observer',
            'juju_model': 'hw-obs',
            'juju_model_uuid': juju_model_uuid,
            'juju_unit': 'hardware-observer/0'
        })

        print('Updated existing job targets to [localhost:10200] for mock server')
        break

if not job_found:
    print('hardware-observer_1_default job not found, creating new job...')
    # Create the new job configuration
    new_job = {
        'job_name': 'hardware-observer_1_default',
        'metrics_path': '/metrics',
        'static_configs': [{
            'targets': ['localhost:10200'],
            'labels': {
                'juju_application': 'hardware-observer',
                'juju_model': 'hw-obs',
                'juju_model_uuid': juju_model_uuid,
                'juju_unit': 'hardware-observer/0'
            }
        }]
    }
    scrape_configs.append(new_job)
    print('Created new hardware-observer_1_default job with mock server target')

# Write back the config with proper permissions
try:
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        yaml.dump(config, temp_file, default_flow_style=False, sort_keys=False)
        temp_path = temp_file.name

    subprocess.run(['mv', temp_path, CONFIG_FILE], check=True)
    print('Successfully patched Grafana Agent config')
except Exception as e:
    print(f'ERROR: Failed to write config file: {e}')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo "Grafana Agent config patched successfully"
else
    echo "Failed to patch Grafana Agent config"
    exit 1
fi

# Verify the patch
echo "=== Verifying patch ==="
grep -A 10 "hardware-observer_1_default" "$CONFIG_FILE" || echo "Job not found after patch"
"""

    patch_action = await hardware_observer_unit.run(patch_config_cmd)
    await patch_action.wait()

    if patch_action.results.get("return-code", 1) == 0:
        logger.info("Grafana Agent config patched successfully")
        logger.info(f"Patch result: {patch_action.results.get('stdout', '')}")
    else:
        logger.error(f"Failed to patch Grafana Agent config: {patch_action.results}")
        raise Exception("Grafana Agent config patching failed")


async def _restore_grafana_agent_config(hardware_observer_unit):
    """Restore original Grafana Agent configuration."""
    logger.info("Restoring original Grafana Agent configuration...")

    restore_cmd = """
BACKUP_FILE="/etc/grafana-agent.yaml.backup"
CONFIG_FILE="/etc/grafana-agent.yaml"

if [ -f "$BACKUP_FILE" ]; then
    sudo cp "$BACKUP_FILE" "$CONFIG_FILE"
    sudo rm "$BACKUP_FILE"
    echo "Restored original Grafana Agent config"
else
    echo "No backup file found, skipping restore"
fi
"""

    restore_action = await hardware_observer_unit.run(restore_cmd)
    await restore_action.wait()
    logger.info(f"Config restore result: {restore_action.results}")


async def _debug_hardware_detection_and_services(hardware_observer_unit):
    """Debug hardware detection and service status in CI environment."""
    logger.info("=== DEBUGGING: Hardware Detection & Services ===")

    # Check if hardware-exporter service exists and its status
    service_debug_cmd = """
echo "=== Service Status ==="
if systemctl list-unit-files | grep -q hardware-exporter.service; then
    echo "hardware-exporter.service EXISTS"
    echo "Status: $(systemctl is-active hardware-exporter.service)"
    echo "Enabled: $(systemctl is-enabled hardware-exporter.service)"
    if [ -f /etc/systemd/system/hardware-exporter.service ]; then
        echo "Service file exists: /etc/systemd/system/hardware-exporter.service"
    else
        echo "Service file missing: /etc/systemd/system/hardware-exporter.service"
    fi
else
    echo "hardware-exporter.service DOES NOT EXIST"
fi
"""
    service_debug_action = await hardware_observer_unit.run(service_debug_cmd)
    await service_debug_action.wait()
    logger.info(f"Service existence: {service_debug_action.results}")

    # Check what's listening on port 10200 and other ports
    port_debug_cmd = """
echo "=== Port Status ==="
echo "Port 10200 specific:"
ss -tulpn | grep :10200 || echo "Nothing listening on port 10200"
echo "All listening ports:"
ss -tulpn | grep LISTEN | head -10
"""
    port_debug_action = await hardware_observer_unit.run(port_debug_cmd)
    await port_debug_action.wait()
    logger.info(f"Port status: {port_debug_action.results}")

    # Check Grafana Agent configuration
    grafana_config_cmd = """
echo "=== Grafana Agent Config ==="
config_file="/etc/grafana-agent.yaml"
echo "Checking config file: $config_file"
if [ -f "$config_file" ]; then
    echo "Config file exists. Checking for port 10200:"
    grep -A 5 -B 5 "10200" "$config_file" || echo "Port 10200 not found in $config_file"
    echo "Hardware-observer jobs:"
    grep -A 15 "hardware-observer.*default" "$config_file" || echo "No hardware-observer jobs found"
    echo "All targets in this file:"
    grep -A 2 -B 1 "targets:" "$config_file" | head -20 || echo "No targets found"
    echo "--- End of $config_file ---"
else
    echo "Config file $config_file not found"
fi
"""
    grafana_debug_action = await hardware_observer_unit.run(grafana_config_cmd)
    await grafana_debug_action.wait()
    logger.info(f"Grafana Agent config: {grafana_debug_action.results}")

    # Check if there are any exporter processes running
    process_debug_cmd = """
echo "=== Running Processes ==="
ps aux | grep -E "(hardware|exporter|prometheus)" | grep -v grep || echo "No exporter processes found"
"""
    process_debug_action = await hardware_observer_unit.run(process_debug_cmd)
    await process_debug_action.wait()
    logger.info(f"Running processes: {process_debug_action.results}")

    logger.info("=== END DEBUGGING ===")


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
    if pip_action.results.get("return-code") == 0:
        logger.info("Pip installation: SUCCESS")
    else:
        logger.error(f"Pip installation failed: {pip_action.results}")

    # Install prometheus_client
    install_deps_cmd = "python3 -m pip install prometheus_client"
    deps_action = await unit.run(install_deps_cmd)
    await deps_action.wait()
    if deps_action.results.get("return-code") == 0:
        logger.info("Dependencies installation: SUCCESS")
    else:
        logger.error(f"Dependencies installation failed: {deps_action.results}")
