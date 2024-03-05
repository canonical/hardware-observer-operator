# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest


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
