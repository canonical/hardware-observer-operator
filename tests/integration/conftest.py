# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os

import pytest
import pytest_asyncio
from juju.controller import Controller
from utils import get_or_add_model

LXD_CTL_NAME = os.environ.get("LXD_CONTROLLER")
K8S_CTL_NAME = os.environ.get("K8S_CONTROLLER")

MODEL_CONFIG = {"logging-config": "<root>=WARNING; unit=DEBUG"}


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str.lower,
        default="jammy",
        choices=["focal", "jammy"],
        help="Set series for the machine units",
    )
    parser.addoption(
        "--channel",
        type=str,
        default="edge",
        choices=["edge", "candidate", "stable"],
        help="Charmhub channel to use during charms deployment",
    )


@pytest.fixture(scope="module")
def series(request):
    return request.config.getoption("--series")


@pytest.fixture(scope="module")
def channel(request):
    return request.config.getoption("--channel")


@pytest_asyncio.fixture()
async def lxd_ctl():
    """Get the controller object referring the lxd controller."""
    if LXD_CTL_NAME is None:
        pytest.fail("LXD_CONTROLLER env variable should be provided")
    lxd_ctl = Controller()
    await lxd_ctl.connect(LXD_CTL_NAME)

    return lxd_ctl


@pytest_asyncio.fixture()
async def k8s_ctl():
    """Get the controller object referring the lxd controller."""
    if K8S_CTL_NAME is None:
        pytest.fail("K8S_CONTROLLER env variable should be provided")
    k8s_ctl = Controller()
    await k8s_ctl.connect(K8S_CTL_NAME)

    return k8s_ctl


@pytest_asyncio.fixture()
async def lxd_model(ops_test, lxd_ctl):
    """Get the model object referring the lxd model."""
    model_name = ops_test.model_name
    lxd_model = await get_or_add_model(ops_test, lxd_ctl, model_name)
    await lxd_model.set_config(MODEL_CONFIG)

    return lxd_model


@pytest_asyncio.fixture()
async def k8s_model(ops_test, k8s_ctl):
    """Get the model object referring the k8s model."""
    model_name = ops_test.model_name
    k8s_model = await get_or_add_model(ops_test, k8s_ctl, model_name)
    await k8s_model.set_config(MODEL_CONFIG)

    return k8s_model
