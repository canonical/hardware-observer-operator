#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

import asyncio
import logging
from enum import Enum
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
PRINCIPAL_APP_NAME = "ubuntu"
GRAFANA_AGENT_APP_NAME = "grafana-agent"

TIMEOUT = 600


class AppStatus(str, Enum):
    """Various workload status messages for the app."""

    INSTALL = "Install complete"
    READY = "Unit is ready"
    MISSING_RELATION = "Missing relation: [cos-agent]"
    UNHEALTHY = "Exporter is unhealthy"
    NOT_RUNNING = "Exporter is not running"
    MISSING_RESOURCES = "Missing resources:"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, series, sync_helper):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    assert charm, "Charm was not built successfully."

    await asyncio.gather(
        ops_test.model.deploy(
            ops_test.render_bundle(
                "tests/functional/bundle.yaml.j2",
                charm=charm,
                series=series,
                resources={
                    "storcli-deb": "empty-resource",
                    "perccli-deb": "empty-resource",
                    "sas2ircu-bin": "empty-resource",
                    "sas3ircu-bin": "empty-resource",
                },
            )
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            timeout=TIMEOUT,
        ),
        ops_test.model.wait_for_idle(
            apps=[GRAFANA_AGENT_APP_NAME],
            status="blocked",
            timeout=TIMEOUT,
        ),
        ops_test.model.wait_for_idle(
            apps=[PRINCIPAL_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
        ),
    )

    # Test initial workload status
    for unit in ops_test.model.applications[APP_NAME].units:
        assert AppStatus.MISSING_RESOURCES not in unit.workload_status_message
        assert unit.workload_status_message == AppStatus.MISSING_RELATION

    for unit in ops_test.model.applications[GRAFANA_AGENT_APP_NAME].units:
        messages = ["grafana-cloud-config: off", "logging-consumer: off", "send-remote-write: off"]
        for msg in messages:
            assert msg in unit.workload_status_message

    check_active_cmd = "systemctl is-active hardware-exporter"

    # Test without cos-agent relation
    for unit in ops_test.model.applications[APP_NAME].units:
        results = await sync_helper.run_command_on_unit(ops_test, unit.name, check_active_cmd)
        assert results.get("return-code") > 0
        assert results.get("stdout").strip() == "inactive"

    # Add cos-agent relation
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
    for unit in ops_test.model.applications[APP_NAME].units:
        results = await sync_helper.run_command_on_unit(ops_test, unit.name, check_active_cmd)
        assert results.get("return-code") == 0
        assert results.get("stdout").strip() == "active"
        assert unit.workload_status_message == AppStatus.READY


class TestCharm:
    """Perform basic functional testing of the charm without having the actual hardware."""

    async def test_00_config_changed_port(self, app, unit, sync_helper, ops_test):
        """Test changing the config option: exporter-port."""
        new_port = "10001"
        await asyncio.gather(
            app.set_config({"exporter-port": new_port}),
            ops_test.model.wait_for_idle(apps=[APP_NAME]),
        )

        cmd = "cat /etc/hardware-exporter-config.yaml"
        results = await sync_helper.run_command_on_unit(ops_test, unit.name, cmd)
        assert results.get("return-code") == 0
        config = yaml.safe_load(results.get("stdout").strip())
        assert config["port"] == int(new_port)

        await app.reset_config(["exporter-port"])

    async def test_01_config_changed_log_level(self, app, unit, sync_helper, ops_test):
        """Test changing the config option: exporter-log-level."""
        new_log_level = "DEBUG"
        await asyncio.gather(
            app.set_config({"exporter-log-level": new_log_level}),
            ops_test.model.wait_for_idle(apps=[APP_NAME]),
        )

        cmd = "cat /etc/hardware-exporter-config.yaml"
        results = await sync_helper.run_command_on_unit(ops_test, unit.name, cmd)
        assert results.get("return-code") == 0
        config = yaml.safe_load(results.get("stdout").strip())
        assert config["level"] == new_log_level

        await app.reset_config(["exporter-log-level"])

    async def test_10_start_and_stop_exporter(self, app, unit, sync_helper, ops_test):
        """Test starting and stopping the exporter results in correct charm status."""
        # Stop the exporter
        stop_cmd = "systemctl stop hardware-exporter"
        async with ops_test.fast_forward():
            await asyncio.gather(
                unit.run(stop_cmd),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.NOT_RUNNING

        # Start the exporter
        start_cmd = "systemctl start hardware-exporter"
        async with ops_test.fast_forward():
            await asyncio.gather(
                unit.run(start_cmd),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.READY

    async def test_11_exporter_failed(self, app, unit, sync_helper, ops_test):
        """Test failure in the exporter results in correct charm status."""
        # Setting incorrect log level will crash the exporter
        async with ops_test.fast_forward():
            await asyncio.gather(
                app.set_config({"exporter-log-level": "RANDOM_LEVEL"}),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.UNHEALTHY

        async with ops_test.fast_forward():
            await asyncio.gather(
                app.reset_config(["exporter-log-level"]),
                ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT),
            )
            assert unit.workload_status_message == AppStatus.READY

    async def test_20_on_remove_event(self, app, sync_helper, ops_test):
        """Test _on_remove event cleans up the service on the host machine."""
        await asyncio.gather(
            app.remove_relation(f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )
        principal_unit = ops_test.model.applications[PRINCIPAL_APP_NAME].units[0]

        cmd = "ls /etc/hardware-exporter-config.yaml"
        results = await sync_helper.run_command_on_unit(ops_test, principal_unit.name, cmd)
        assert results.get("return-code") > 0

        cmd = "ls /etc/systemd/system/hardware-exporter.service"
        results = await sync_helper.run_command_on_unit(ops_test, principal_unit.name, cmd)
        assert results.get("return-code") > 0

        await asyncio.gather(
            ops_test.model.add_relation(
                f"{APP_NAME}:general-info", f"{PRINCIPAL_APP_NAME}:juju-info"
            ),
            ops_test.model.wait_for_idle(
                apps=[PRINCIPAL_APP_NAME], status="active", timeout=TIMEOUT
            ),
        )
