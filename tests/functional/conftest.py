import logging
import platform

import pytest
from utils import RESOURCES_DIR, Resource

from config import HARDWARE_EXPORTER_COLLECTOR_MAPPING, TPR_RESOURCES, HWTool

log = logging.getLogger(__name__)


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
def architecture():
    machine = platform.machine()
    if machine == "aarch64":
        return "arm64"
    return "amd64"


@pytest.fixture(scope="module")
def provided_collectors(request):
    return set(request.config.getoption("collectors"))


def pytest_configure(config):
    config.addinivalue_line("markers", "realhw: mark test as requiring real hardware to run.")


def pytest_collection_modifyitems(config, items):
    if config.getoption("collectors"):
        # --collectors provided, skip hw independent tests
        skip_hw_independent = pytest.mark.skip(
            reason="Hardware independent tests are skipped since --collectors was provided."
        )
        for item in items:
            # skip TestCharm tests where "realhw" marker is not present
            # we don't want to skip test_setup_and_build, test_required_resources,
            # test_cos_agent_relation and test_redfish_credential_validation
            # even for hw independent tests
            # so we also check for the abort_on_fail marker
            if "realhw" not in item.keywords and "abort_on_fail" not in item.keywords:
                item.add_marker(skip_hw_independent)
    else:
        # skip hw dependent tests in TestCharmWithHW marked with "realhw"
        skip_hw_dependent = pytest.mark.skip(
            reason="Hardware dependent test. Provide collectors with the --collectors option."
        )
        for item in items:
            if "realhw" in item.keywords:
                item.add_marker(skip_hw_dependent)


@pytest.fixture()
def app(ops_test):
    return ops_test.model.applications["hardware-observer"]


@pytest.fixture()
def unit(app):
    return app.units[0]


@pytest.fixture()
def resources() -> list[Resource]:
    """Return list of Resource objects."""
    return [
        Resource(
            resource_name=TPR_RESOURCES.get(HWTool.STORCLI),
            file_name="storcli.deb",
            collector_name=HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(HWTool.STORCLI).replace(
                "collector.", ""
            ),
            bin_name=HWTool.STORCLI.value,
        ),
        Resource(
            resource_name=TPR_RESOURCES.get(HWTool.PERCCLI),
            file_name="perccli.deb",
            collector_name=HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(HWTool.PERCCLI).replace(
                "collector.", ""
            ),
            bin_name=HWTool.PERCCLI.value,
        ),
        Resource(
            resource_name=TPR_RESOURCES.get(HWTool.SAS2IRCU),
            file_name="sas2ircu",
            collector_name=HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(HWTool.SAS2IRCU).replace(
                "collector.", ""
            ),
            bin_name=HWTool.SAS2IRCU.value,
        ),
        Resource(
            resource_name=TPR_RESOURCES.get(HWTool.SAS3IRCU),
            file_name="sas3ircu",
            collector_name=HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(HWTool.SAS3IRCU).replace(
                "collector.", ""
            ),
            bin_name=HWTool.SAS3IRCU.value,
        ),
    ]


@pytest.fixture()
def required_resources(resources: list[Resource], provided_collectors: set) -> list[Resource]:
    """Return list of required resources to be attached as per hardware availability.

    Required resources will be empty if no collectors are provided.
    """
    required_resources = []

    for resource in resources:
        if resource.collector_name in provided_collectors:
            resource.file_path = f"{RESOURCES_DIR}/{resource.file_name}"
            required_resources.append(resource)

    return required_resources
