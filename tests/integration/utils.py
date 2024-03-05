# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from juju.controller import Controller
from juju.model import Model
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def get_or_add_model(ops_test: OpsTest, controller: Controller, model_name: str) -> Model:
    if model_name not in await controller.get_models():
        await controller.add_model(model_name)
        ctl_name = controller.controller_name
        await ops_test.track_model(
            f"{ctl_name}-{model_name}", cloud_name=ctl_name, model_name=model_name, keep=False
        )

    return await controller.get_model(model_name)
