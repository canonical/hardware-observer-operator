import logging

import pytest

log = logging.getLogger(__name__)


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
