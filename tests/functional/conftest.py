import logging

import pytest
from async_lru import alru_cache

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

    @staticmethod
    @alru_cache
    async def get_metrics_output(ops_test, unit_name):
        """Return prometheus metric output from endpoint on unit."""
        port = 10200
        command = f"curl localhost:{port}"
        results = await SyncHelper.run_command_on_unit(ops_test, unit_name, command)
        return results


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str.lower,
        default="jammy",
        choices=["focal", "jammy"],
        help="Set series for the machine units",
    )

    parser.addoption(
        "--collectors",
        nargs="+",
        type=str.lower,
        default="",
        choices=[
            "ipmi_dcmi",
            "ipmi_sel",
            "ipmi_sensor",
            "redfish",
            "mega_raid",
            "poweredge_raid",
            "lsi_sas_2",
            "lsi_sas_3",
        ],
        help="Provide space-separated list of collectors for testing with real hardware.",
    )


@pytest.fixture(scope="module")
def series(request):
    return request.config.getoption("--series")


@pytest.fixture(scope="module")
def provided_collectors(request):
    return request.config.getoption("collectors")


def pytest_configure(config):
    config.addinivalue_line("markers", "realhw: mark test as requiring real hardware to run.")


def pytest_collection_modifyitems(config, items):
    if config.getoption("collectors"):
        # --collectors provided, do not skip tests
        return
    skip_real_hw = pytest.mark.skip(
        reason="Hardware dependent test. Provide collectors with the --collectors option."
    )
    for item in items:
        if "realhw" in item.keywords:
            item.add_marker(skip_real_hw)


@pytest.fixture(scope="module")
def sync_helper():
    return SyncHelper


@pytest.fixture()
def app(ops_test):
    return ops_test.model.applications["hardware-observer"]


@pytest.fixture()
def unit(app):
    return app.units[0]
