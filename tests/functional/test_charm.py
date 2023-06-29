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


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, series, helper):
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
        assert unit.workload_status_message == AppStatus.MISSING_RELATION
    for unit in ops_test.model.applications[GRAFANA_AGENT_APP_NAME].units:
        message = "Missing relation: [send-remote-write|grafana-cloud-config]"
        assert unit.workload_status_message == message

    # Test without cos-agent relation
    for unit in ops_test.model.applications[APP_NAME].units:
        check_active_cmd = "systemctl is-active hardware-exporter"
        results = await helper.run_wait(unit, check_active_cmd)
        assert results.get("return-code") == 3
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
        check_active_cmd = "systemctl is-active hardware-exporter"
        results = await helper.run_wait(unit, check_active_cmd)
        assert results.get("return-code") == 0
        assert results.get("stdout").strip() == "active"
        assert unit.workload_status_message == AppStatus.READY
