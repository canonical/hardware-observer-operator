import inspect
import logging
import os
import platform
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest
from utils import RESOURCES_DIR, Resource

from config import HARDWARE_EXPORTER_COLLECTOR_MAPPING, TPR_RESOURCES, HWTool

log = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--base",
        type=str.lower,
        default="ubuntu@22.04",
        choices=["ubuntu@20.04", "ubuntu@22.04", "ubuntu@24.04"],
        help="Set base for the applications.",
    )

    parser.addoption(
        "--realhw",
        action="store_true",
        help="Enable real hardware testing.",
    )

    parser.addoption(
        "--nvidia",
        action="store_true",
        help="Enable NVIDIA GPU support for testing with real hardware.",
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


def get_this_script_dir() -> Path:
    filename = inspect.getframeinfo(inspect.currentframe()).filename  # type: ignore[arg-type]
    path = os.path.dirname(os.path.abspath(filename))
    return Path(path)


@pytest.fixture(scope="module")
def bundle(ops_test: OpsTest, request, charm_path, base, provided_collectors):
    """Configure the bundle depending on cli arguments."""
    bundle_template_path = get_this_script_dir() / "bundle.yaml.j2"
    log.info("Rendering bundle %s", bundle_template_path)
    bundle = ops_test.render_bundle(
        bundle_template_path,
        charm=charm_path,
        base=base,
        redfish_disable=("redfish" not in provided_collectors),
        resources={
            "storcli-deb": "empty-resource",
            "perccli-deb": "empty-resource",
            "sas2ircu-bin": "empty-resource",
            "sas3ircu-bin": "empty-resource",
        },
    )

    return bundle


@pytest.fixture(scope="module")
def base(request):
    return request.config.getoption("--base")


@pytest.fixture(scope="module")
def nvidia_present(request):
    return request.config.getoption("--nvidia")


@pytest.fixture(scope="module")
def realhw(request):
    return request.config.getoption("--realhw")


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
    if not config.getoption("--realhw"):
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


@pytest.fixture(scope="module")
def charm_path(base: str, architecture: str) -> Path:
    """Fixture to determine the charm path based on the base and architecture."""
    glob_path = f"hardware-observer_*{base}-{architecture}*.charm"
    paths = list(Path(".").glob(glob_path))

    if not paths:
        raise FileNotFoundError(f"The path for the charm for {base}-{architecture} is not found.")

    if len(paths) > 1:
        raise FileNotFoundError(
            f"Multiple charms found for {base}-{architecture}. Please provide only one."
        )

    # The bundle will need the full path to the charm
    path = paths[0].absolute()
    log.info(f"Using charm path: {path}")
    return path
