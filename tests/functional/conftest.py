import logging

import pytest

log = logging.getLogger(__name__)


class SyncHelper:
    """Helper class for running juju async function."""

    @staticmethod
    async def run_command_on_unit(ops_test, unit_name, command):
        complete_command = ["exec", "--unit", unit_name, "--", *command.split()]
        return_code, stdout, _ = await ops_test.juju(*complete_command)
        results = {
            "return-code": return_code,
            "stdout": stdout,
        }
        return results


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str.lower,
        default="jammy",
        choices=["focal", "jammy"],
        help="Set series for the machine units",
    )


@pytest.fixture(scope="module")
def series(request):
    return request.config.getoption("--series")


@pytest.fixture(scope="module")
def sync_helper():
    return SyncHelper


@pytest.fixture()
def app(ops_test):
    return ops_test.model.applications["hardware-observer"]


@pytest.fixture()
def unit(app):
    return app.units[0]
