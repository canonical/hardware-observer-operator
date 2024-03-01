#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

import asyncio
import inspect
import logging
import os
from enum import Enum
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, retry_if_result, stop_after_attempt, wait_fixed
from utils import RESOURCES_DIR, get_metrics_output, parse_metrics, run_command_on_unit

from config import TOOLS_DIR

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
PRINCIPAL_APP_NAME = "ubuntu"
GRAFANA_AGENT_APP_NAME = "grafana-agent"

TIMEOUT = 600


def get_this_script_dir() -> Path:
    filename = inspect.getframeinfo(inspect.currentframe()).filename  # type: ignore[arg-type]
    path = os.path.dirname(os.path.abspath(filename))
    return Path(path)


class AppStatus(str, Enum):
    """Various workload status messages for the app."""

    INSTALL = "Install complete"
    READY = "Unit is ready"
    MISSING_RELATION = "Missing relation: [cos-agent]"
    NOT_RUNNING = "Exporter is not running"
    MISSING_RESOURCES = "Missing resources:"
    CHECKSUM_ERROR = "Fail strategies: "
    INVALID_CONFIG_EXPORTER_LOG_LEVEL = "Invalid config: 'exporter-log-level'"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(  # noqa: C901, function is too complex
    ops_test: OpsTest, series, provided_collectors, required_resources
):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    Optionally attach required resources when testing with real hardware.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    assert charm, "Charm was not built successfully."

    bundle_template_path = get_this_script_dir() / "bundle.yaml.j2"

    logger.info("Rendering bundle %s", bundle_template_path)
    bundle = ops_test.render_bundle(
        bundle_template_path,
        charm=charm,
        series=series,
        resources={
            "storcli-deb": "empty-resource",
            "perccli-deb": "empty-resource",
            "sas2ircu-bin": "empty-resource",
            "sas3ircu-bin": "empty-resource",
        },
    )

    juju_cmd = ["deploy", "-m", ops_test.model_full_name, str(bundle)]

    # deploy bundle to already added machine instead of provisioning new one
    # when testing with real hardware
    if provided_collectors:
        juju_cmd.append("--map-machines=existing")

    logging.info("Deploying bundle...")
    rc, stdout, stderr = await ops_test.juju(*juju_cmd)
    assert rc == 0, f"Bundle deploy failed: {(stderr or stdout).strip()}"

    await ops_test.model.wait_for_idle(
        apps=[PRINCIPAL_APP_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=TIMEOUT,
    )
    await ops_test.model.wait_for_idle(
        apps=[GRAFANA_AGENT_APP_NAME],
        status="blocked",
        timeout=TIMEOUT,
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=TIMEOUT,
    )

    if required_resources:
        logging.info(
            f"Required resources to attach: {[r.resource_name for r in required_resources]}"
        )
        # check workload status for real hardware based tests requiring resources to be attached
        for unit in ops_test.model.applications[APP_NAME].units:
            assert AppStatus.MISSING_RESOURCES in unit.workload_status_message

        # NOTE: resource files need to be manually placed into the resources directory
        for resource in required_resources:
            path = f"{RESOURCES_DIR}/{resource.file_name}"
            if not Path(path).exists():
                pytest.fail(f"{path} not provided. Add resource into {RESOURCES_DIR} directory")
            resource.file_path = path

        resource_path_map = {r.resource_name: r.file_path for r in required_resources}
        resource_cmd = [f"{name}={path}" for name, path in resource_path_map.items()]
        juju_cmd = ["attach-resource", APP_NAME, "-m", ops_test.model_full_name] + resource_cmd

        logging.info("Attaching resources...")
        rc, stdout, stderr = await ops_test.juju(*juju_cmd)
        assert rc == 0, f"Attaching resources failed: {(stderr or stdout).strip()}"

        # still blocked since cos-agent relation has not been added
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            timeout=TIMEOUT,
        )

    # Test workload status with no real hardware or
    # when real hardware doesn't require any resource to be attached
    for unit in ops_test.model.applications[APP_NAME].units:
        assert AppStatus.MISSING_RESOURCES not in unit.workload_status_message
        assert unit.workload_status_message == AppStatus.MISSING_RELATION

    for unit in ops_test.model.applications[GRAFANA_AGENT_APP_NAME].units:
        messages = ["grafana-cloud-config: off", "logging-consumer: off", "send-remote-write: off"]
        for msg in messages:
            assert msg in unit.workload_status_message

    check_active_cmd = "systemctl is-active hardware-exporter"

    # Test without cos-agent relation
    logging.info("Check whether hardware-exporter is inactive before creating relation.")
    for unit in ops_test.model.applications[APP_NAME].units:
        results = await run_command_on_unit(ops_test, unit.name, check_active_cmd)
        assert results.get("return-code") > 0
        assert results.get("stdout").strip() == "inactive"

    # Add cos-agent relation
    logging.info("Adding cos-agent relation.")
    await asyncio.gather(
        ops_test.model.add_relation(
            f"{APP_NAME}:cos-agent", f"{GRAFANA_AGENT_APP_NAME}:cos-agent"
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            timeout=TIMEOUT,
        ),
    )

    # Test with cos-agent relation
    logging.info("Check whether hardware-exporter is active after creating relation.")
    for unit in ops_test.model.applications[APP_NAME].units:
        results = await run_command_on_unit(ops_test, unit.name, check_active_cmd)
        assert results.get("return-code") == 0
        assert results.get("stdout").strip() == "active"
        assert unit.workload_status_message == AppStatus.READY


@pytest.mark.realhw
class TestCharmWithHW:
    """Run functional tests that require specific hardware."""

    async def test_config_collector_enabled(self, app, unit, ops_test, provided_collectors):
        """Test whether provided collectors are present in exporter config."""
        cmd = "cat /etc/hardware-exporter-config.yaml"
        results = await run_command_on_unit(ops_test, unit.name, cmd)
        assert results.get("return-code") == 0
        config = yaml.safe_load(results.get("stdout").strip())
        collectors_in_config = {
            collector.replace("collector.", "") for collector in config.get("enable_collectors")
        }
        error_msg = (
            f"Provided collectors {provided_collectors} are different from"
            f" enabled collectors in config {collectors_in_config}"
        )
        assert provided_collectors == collectors_in_config, error_msg

    async def test_metrics_available(self, app, unit, ops_test):
        """Test if metrics are available at the expected endpoint on unit."""
        results = await get_metrics_output(ops_test, unit.name)
        assert results.get("return-code") == 0, "Metrics output not available"

    @pytest.mark.parametrize(
        "collector",
        [
            "ipmi_dcmi",
            "ipmi_sel",
            "ipmi_sensor",
            "redfish",
            "poweredge_raid",
            "mega_raid",
            "lsi_sas_2",
            "lsi_sas_3",
        ],
    )
    async def test_collector_specific_metrics_available(
        self, ops_test, app, unit, provided_collectors, collector
    ):
        """Test if metrics specific to provided collectors are present."""
        if collector not in provided_collectors:
            pytest.skip(f"{collector} not in provided collectors, skipping test")

        # collector is available, proceed to run collector specific tests
        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        assert parsed_metrics.get(collector), f"{collector} specific metrics are not available."

    async def test_resource_in_correct_location(self, ops_test, unit, required_resources):
        """Test if attached resource is added to correctly specified location."""
        # by default, TOOLS_DIR = Path("/usr/sbin")
        for resource in required_resources:
            symlink_bin = TOOLS_DIR / resource.bin_name
            # checks whether symlink points correctly resource binary
            check_resource_cmd = f"ls -L {symlink_bin}"
            results = await run_command_on_unit(ops_test, unit.name, check_resource_cmd)
            assert results.get("return-code") == 0, f"{symlink_bin} resource doesn't exist"

    async def test_wrong_resource_attached(self, ops_test, unit, required_resources, tmp_path):
        """Test charm when wrong resource file for collector has been attached."""
        for resource in required_resources:
            # resource file names require the right extensions
            if resource.resource_name in ["storcli-deb", "perccli-deb"]:
                tmp_resource_file = tmp_path / "resource.deb"
            else:
                tmp_resource_file = tmp_path / "resource"

            # write random data into file
            with open(tmp_resource_file, "w") as file:
                file.write(str(uuid4()))

            logging.info(f"Testing wrong resource for: {resource.resource_name}")
            juju_cmd = [
                "attach-resource",
                APP_NAME,
                "-m",
                ops_test.model_full_name,
                f"{resource.resource_name}={tmp_resource_file}",
            ]
            rc, stdout, stderr = await ops_test.juju(*juju_cmd)
            assert rc == 0, f"Attaching resource failed: {(stderr or stdout).strip()}"

            await ops_test.model.wait_for_idle(
                apps=[APP_NAME],
                status="blocked",
                timeout=TIMEOUT,
            )
            assert AppStatus.CHECKSUM_ERROR in unit.workload_status_message

            resource_path = f"{RESOURCES_DIR}/{resource.file_name}"
            if not Path(resource_path).exists():
                pytest.fail(f"{resource_path} doesn't exist.")

            # reset test environment by reattaching correct resource
            logging.info("Re-attaching correct resource...")
            juju_cmd = [
                "attach-resource",
                APP_NAME,
                "-m",
                ops_test.model_full_name,
                f"{resource.resource_name}={resource_path}",
            ]
            # check if attaching resource failed so that it doesn't impact the test for the
            # next resource
            rc, stdout, stderr = await ops_test.juju(*juju_cmd)
            assert rc == 0, f"Attaching resource failed: {(stderr or stdout).strip()}"

            await ops_test.model.wait_for_idle(
                apps=[APP_NAME],
                status="active",
                timeout=TIMEOUT,
            )
            assert AppStatus.MISSING_RESOURCES not in unit.workload_status_message

    async def test_resource_clean_up(self, ops_test, app, unit, required_resources):
        """Test resource clean up behaviour when relation with principal charm is removed."""
        await asyncio.gather(
            app.remove_relation(f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )
        principal_unit = ops_test.model.applications[PRINCIPAL_APP_NAME].units[0]

        # Wait for cleanup activities to finish
        await ops_test.model.block_until(
            lambda: ops_test.model.applications[APP_NAME].status == "unknown"
        )

        for resource in required_resources:
            symlink_bin = TOOLS_DIR / resource.bin_name
            check_resource_cmd = f"ls -L {symlink_bin}"
            results = await run_command_on_unit(ops_test, principal_unit.name, check_resource_cmd)
            assert results.get("return-code") > 0, f"{symlink_bin} resource has not been removed"

        # reset test environment by adding ubuntu:juju-info relation again
        await asyncio.gather(
            ops_test.model.add_relation(
                f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"
            ),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )

    async def test_redfish_metrics(self, ops_test, app, unit, provided_collectors):  # noqa: C901
        """Tests for redfish specific metrics."""
        if "redfish" not in provided_collectors:
            pytest.skip("redfish not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("redfish"):
            if metric.name == "redfish_service_available":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"
            elif metric.name == "redfish_call_success":
                assert metric.value == 0.0, f"{metric.name} value is incorrect"

        # fetch and configure redfish creds
        logging.info("Setting Redfish credentials...")
        username = os.getenv("REDFISH_USERNAME")
        password = os.getenv("REDFISH_PASSWORD")
        if username is None or password is None:
            pytest.fail("Environment vars for redfish creds not set")
        await asyncio.gather(
            app.set_config({"redfish-username": username}),
            app.set_config({"redfish-password": password}),
            ops_test.model.wait_for_idle(apps=[APP_NAME]),
        )

        logging.info("Check metric after setting redfish credentials...")
        try:
            # retry metric endpoint check which takes some time to settle after config change
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_fixed(5),
                retry=retry_if_result(lambda r: r != 0),
            ):
                with attempt:
                    logging.info(f"Attempt #{attempt.retry_state.attempt_number}")
                    get_metrics_output.cache_clear()  # don't hit cache, need new redfish metrics
                    results = await get_metrics_output(ops_test, unit.name)
                    await ops_test.model.wait_for_idle(apps=[APP_NAME])
                if not attempt.retry_state.outcome.failed:
                    attempt.retry_state.set_result(results["return-code"])
        except RetryError:
            pytest.fail("Not able to obtain metrics.")

        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("redfish"):
            if metric.name == "redfish_call_success":
                assert metric.value == 1.0, f"{metric.name} should be 1.0 after login."

    async def test_poweredge_raid_metrics(self, ops_test, unit, provided_collectors):
        """Tests for poweredge_raid specific metrics."""
        if "poweredge_raid" not in provided_collectors:
            pytest.skip("poweredge_raid not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("poweredge_raid"):
            if metric.name == "perccli_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"
            elif metric.name == "perccli_command_ctrl_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    async def test_mega_raid_metrics(self, ops_test, unit, provided_collectors):
        """Tests for mega_raid specific metrics."""
        if "mega_raid" not in provided_collectors:
            pytest.skip("mega_raid not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("mega_raid"):
            if metric.name == "storcli_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    async def test_ipmi_dcmi_metrics(self, ops_test, unit, provided_collectors):
        """Tests for ipmi_dcmi specific metrics."""
        if "ipmi_dcmi" not in provided_collectors:
            pytest.skip("ipmi_dcmi not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("ipmi_dcmi"):
            if metric.name == "ipmi_dcmi_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    async def test_ipmi_sensor_metrics(self, ops_test, unit, provided_collectors):
        """Tests for ipmi_sensor specific metrics."""
        if "ipmi_sensor" not in provided_collectors:
            pytest.skip("ipmi_sensor not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("ipmi_sensor"):
            if metric.name == "ipmimonitoring_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    async def test_ipmi_sel_metrics(self, ops_test, unit, provided_collectors):
        """Tests for ipmi_sel specific metrics."""
        if "ipmi_sel" not in provided_collectors:
            pytest.skip("ipmi_sel not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("ipmi_sel"):
            if metric.name == "ipmi_sel_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    @pytest.mark.parametrize("version", ["1", "2"])
    async def test_lsi_sas_metrics(self, ops_test, unit, provided_collectors, version):
        """Tests for lsi_sas_{1,2} specific metrics."""
        collector = f"lsi_sas_{version}"
        if collector not in provided_collectors:
            pytest.skip(f"{collector} not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get(collector):
            if metric.name == f"sas{version}ircu_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"

    async def test_hpe_ssa_metrics(self, ops_test, unit, provided_collectors):
        """Tests for hpe_ssa specific metrics."""
        if "hpe_ssa" not in provided_collectors:
            pytest.skip("hpe_ssa not in provided collectors, skipping test")

        results = await get_metrics_output(ops_test, unit.name)
        parsed_metrics = parse_metrics(results.get("stdout").strip())
        for metric in parsed_metrics.get("hpe_ssa"):
            if metric.name == "ssacli_command_success":
                assert metric.value == 1.0, f"{metric.name} value is incorrect"


class TestCharm:
    """Perform basic functional testing of the charm without having the actual hardware."""

    async def test_config_changed_port(self, app, unit, ops_test):
        """Test changing the config option: exporter-port."""
        new_port = "10001"
        await asyncio.gather(
            app.set_config({"exporter-port": new_port}),
            ops_test.model.wait_for_idle(apps=[APP_NAME]),
        )

        cmd = "cat /etc/hardware-exporter-config.yaml"
        results = await run_command_on_unit(ops_test, unit.name, cmd)
        assert results.get("return-code") == 0
        config = yaml.safe_load(results.get("stdout").strip())
        assert config["port"] == int(new_port)

        await app.reset_config(["exporter-port"])

    async def test_config_changed_log_level(self, app, unit, ops_test):
        """Test changing the config option: exporter-log-level."""
        new_log_level = "DEBUG"
        await asyncio.gather(
            app.set_config({"exporter-log-level": new_log_level}),
            ops_test.model.wait_for_idle(apps=[APP_NAME]),
        )

        cmd = "cat /etc/hardware-exporter-config.yaml"
        results = await run_command_on_unit(ops_test, unit.name, cmd)
        assert results.get("return-code") == 0
        config = yaml.safe_load(results.get("stdout").strip())
        assert config["level"] == new_log_level

        await app.reset_config(["exporter-log-level"])

    async def test_start_and_stop_exporter(self, app, unit, ops_test):
        """Test starting and stopping the exporter results in correct charm status."""
        # Stop the exporter, and the exporter should auto-restart after update status fire.
        stop_cmd = "systemctl stop hardware-exporter"
        async with ops_test.fast_forward():
            await asyncio.gather(
                unit.run(stop_cmd),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.READY

    async def test_exporter_failed(self, app, unit, ops_test):
        """Test failure in the exporter results in correct charm status."""
        # Setting incorrect log level will crash the exporter
        async with ops_test.fast_forward():
            await asyncio.gather(
                app.set_config({"exporter-log-level": "RANDOM_LEVEL"}),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.INVALID_CONFIG_EXPORTER_LOG_LEVEL

        async with ops_test.fast_forward():
            await asyncio.gather(
                app.reset_config(["exporter-log-level"]),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.READY

    async def test_on_remove_event(self, app, ops_test):
        """Test _on_remove event cleans up the service on the host machine."""
        await asyncio.gather(
            app.remove_relation(f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )
        principal_unit = ops_test.model.applications[PRINCIPAL_APP_NAME].units[0]

        # Wait for cleanup activities to finish
        await ops_test.model.block_until(
            lambda: ops_test.model.applications[APP_NAME].status == "unknown"
        )

        cmd = "ls /etc/hardware-exporter-config.yaml"
        results = await run_command_on_unit(ops_test, principal_unit.name, cmd)
        assert results.get("return-code") > 0

        cmd = "ls /etc/systemd/system/hardware-exporter.service"
        results = await run_command_on_unit(ops_test, principal_unit.name, cmd)
        assert results.get("return-code") > 0

        await asyncio.gather(
            ops_test.model.add_relation(
                f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"
            ),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )
