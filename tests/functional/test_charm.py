#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

PRINCIPAL_APP_NAME = "ubuntu"

TIMEOUT = 600


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, series):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")

    await asyncio.gather(
        ops_test.model.deploy(
            PRINCIPAL_APP_NAME,
            application_name=PRINCIPAL_APP_NAME,
            channel="stable",
            series=series,
        ),
        ops_test.model.wait_for_idle(
            apps=[PRINCIPAL_APP_NAME], status="active", raise_on_blocked=True, timeout=TIMEOUT
        ),
    )

    # Deploy the charm and wait for active/idle status
    await ops_test.model.deploy(charm, application_name=APP_NAME, num_units=0)
    await ops_test.model.add_relation(
        f"{PRINCIPAL_APP_NAME}:juju-info", f"{APP_NAME}:general-info"
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=TIMEOUT
    )
