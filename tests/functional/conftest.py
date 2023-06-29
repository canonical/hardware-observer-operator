import logging

import pytest

log = logging.getLogger(__name__)


class Helper:
    """Helper class for async functions."""

    @staticmethod
    async def run_wait(unit, command):
        action = await unit.run(command)
        await action.wait()
        return action.results


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str,
        default="jammy",
        help="Set series for the machine units",
    )


@pytest.fixture(scope="module")
def series(request):
    return request.config.getoption("--series")


@pytest.fixture(scope="module")
def helper():
    return Helper
