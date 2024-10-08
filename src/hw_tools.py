"""Helper for hardware tools.

Define strategy for install, remove and verifier for different hardware.
"""

import logging
import os
import re
import shutil
import stat
import subprocess
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import List, Set

import requests
import urllib3
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from ops.model import Resources

import apt_helpers
from checksum import (
    PERCCLI_VERSION_INFOS,
    SAS2IRCU_VERSION_INFOS,
    SAS3IRCU_VERSION_INFOS,
    STORCLI_VERSION_INFOS,
    ResourceChecksumError,
    validate_checksum,
)
from config import (
    HARDWARE_EXPORTER_SETTINGS,
    SNAP_COMMON,
    TOOLS_DIR,
    TPR_RESOURCES,
    HWTool,
    StorageVendor,
    SystemVendor,
)
from hardware import (
    HWINFO_SUPPORTED_STORAGES,
    LSHW_SUPPORTED_STORAGES,
    get_bmc_address,
    hwinfo,
    lshw,
)
from keys import HP_KEYS

logger = logging.getLogger(__name__)

# We know what we are doing: this is only for verification purpose.
# See `redfish_available` function.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ResourceFileSizeZeroError(Exception):
    """Empty resource error."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"Tool: {tool} path: {path} size is zero"


class ResourceInstallationError(Exception):
    """Exception raised when a hardware tool installation fails."""

    def __init__(self, tool: HWTool):
        """Init."""
        super().__init__(f"Installation failed for tool: {tool}")


def copy_to_snap_common_bin(source: Path, filename: str) -> None:
    """Copy file to $SNAP_COMMON/bin folder."""
    Path(f"{SNAP_COMMON}/bin").mkdir(parents=False, exist_ok=True)
    shutil.copy(source, f"{SNAP_COMMON}/bin/{filename}")


def symlink(src: Path, dst: Path) -> None:
    """Create softlink."""
    try:
        dst.unlink(missing_ok=True)  # Remove file if exists
        dst.symlink_to(src)
    except OSError as err:
        logger.exception(err)
        raise


def file_is_empty(path: Path) -> bool:
    """Check whether file size is 0.

    Returns True if file is empty, otherwise returns False.

    Third-party resources are not allowed to be redistributed on Charmhub.
    Therefore, an empty file is uploaded as a resource which the user is expected
    to replace. This function checks for those empty resource files.
    """
    if path.stat().st_size == 0:
        logger.info("%s size is 0", path)
        return True
    return False


def install_deb(name: str, path: Path) -> None:
    """Install local deb package."""
    _cmd: List[str] = ["dpkg", "-i", str(path)]
    try:
        result = subprocess.check_output(_cmd, universal_newlines=True)
        logger.debug(result)
        logger.info("Install deb package %s from %s success", name, path)
    except subprocess.CalledProcessError as exc:
        raise apt.PackageError(f"Fail to install deb {name} from {path}") from exc


def remove_deb(pkg: str) -> None:
    """Remove deb package."""
    _cmd: List[str] = ["dpkg", "--remove", pkg]
    try:
        result = subprocess.check_output(_cmd, universal_newlines=True)
        logger.debug(result)
        logger.info("Remove deb package %s", pkg)
    except subprocess.CalledProcessError as exc:
        raise apt.PackageError(f"Fail to remove deb {pkg}") from exc


def make_executable(src: Path) -> None:
    """Make src executable."""
    uid = 0
    gid = 0
    try:
        os.chmod(src, stat.S_IEXEC)
        os.chown(src, uid, gid)
    except OSError as err:
        logger.error(err)
        raise err


def check_deb_pkg_installed(pkg: str) -> bool:
    """Check if debian package is installed."""
    try:
        apt.DebianPackage.from_installed_package(pkg)
        return True
    except apt.PackageNotFoundError:
        logger.warning("package %s not found in installed package", pkg)
    return False


class StrategyABC(metaclass=ABCMeta):  # pylint: disable=R0903
    """Basic strategy."""

    _name: HWTool

    @property
    def name(self) -> HWTool:
        """Name."""
        return self._name

    @abstractmethod
    def check(self) -> bool:
        """Check installation status of the tool."""

    def install(self) -> None:
        """Installation details."""

    def remove(self) -> None:
        """Remove details."""


class TPRStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Third party resource strategy class."""

    resources: Resources

    def __init__(self, resources: Resources) -> None:
        """Inject the Resource object for fetching resource."""
        self.resources = resources

    def _fetch_tool(self) -> Path:
        path = self.resources.fetch(TPR_RESOURCES[self._name])
        if path is None or file_is_empty(path):
            logger.info("Skipping %s resource install since empty file was detected.", self.name)
            raise ResourceFileSizeZeroError(tool=self._name, path=path)
        return path


class SnapStrategy(StrategyABC):
    """Snap strategy class."""

    channel: str

    @property
    def snap_name(self) -> str:
        """Snap name."""
        return self._name.value

    @property
    def snap_common(self) -> Path:
        """Snap common directory."""
        return Path(f"/var/snap/{self.snap_name}/common/")

    @property
    def snap_client(self) -> snap.Snap:
        """Return the snap client."""
        return snap.SnapCache()[self.snap_name]

    def install(self) -> None:
        """Install the snap from a channel."""
        try:
            snap.add(self.snap_name, channel=self.channel)
            logger.info("Installed %s from channel: %s", self.snap_name, self.channel)

        # using the snap.SnapError will result into:
        # TypeError: catching classes that do not inherit from BaseException is not allowed
        except Exception as err:  # pylint: disable=broad-except
            logger.error(
                "Failed to install %s from channel: %s: %s", self.snap_name, self.channel, err
            )
            raise err

    def remove(self) -> None:
        """Remove the snap."""
        try:
            snap.remove([self.snap_name])

        # using the snap.SnapError will result into:
        # TypeError: catching classes that do not inherit from BaseException is not allowed
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Failed to remove %s: %s", self.snap_name, err)
            raise err

    def check(self) -> bool:
        """Check if all services are active."""
        return all(
            service.get("active", False)
            for service in snap.SnapCache()[self.snap_name].services.values()
        )


class DCGMExporterStrategy(SnapStrategy):
    """DCGM exporter strategy class."""

    _name = HWTool.DCGM
    metric_file = Path.cwd() / "src/gpu_metrics/dcgm_metrics.csv"

    def __init__(self, channel: str) -> None:
        """Init."""
        self.channel = channel

    def install(self) -> None:
        """Install the snap and the custom metrics."""
        super().install()
        self._create_custom_metrics()

    def _create_custom_metrics(self) -> None:
        logger.info("Creating a custom metrics file and configuring the DCGM snap to use it")
        try:
            shutil.copy(self.metric_file, self.snap_common)
            self.snap_client.set({"dcgm-exporter-metrics-file": self.metric_file.name})
            self.snap_client.restart(reload=True)
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Failed to configure custom DCGM metrics: %s", err)
            raise err


class NVIDIADriverStrategy(StrategyABC):
    """NVIDIA driver strategy class."""

    _name = HWTool.NVIDIA_DRIVER
    installed_pkgs = Path("/tmp/nvidia-installed-pkgs.txt")
    pkg_pattern = r"nvidia(?:-[a-zA-Z-]*)?-(\d+)(?:-[a-zA-Z]*)?"

    def install(self) -> None:
        """Install the driver and NVIDIA utils."""
        self._install_nvidia_drivers()
        self._install_nvidia_utils()

    def _install_nvidia_drivers(self) -> None:
        """Install the NVIDIA driver if not present."""
        if Path("/proc/driver/nvidia/version").exists():
            logger.info("NVIDIA driver already installed in the machine")
            return

        logger.info("Installing NVIDIA driver")
        apt.add_package("ubuntu-drivers-common", update_cache=True)

        # output what driver was installed helps gets the version installed later
        cmd = f"ubuntu-drivers install --gpgpu --package-list {self.installed_pkgs}"
        try:
            # This can be changed to check_call and not rely in the output if this is fixed
            # https://github.com/canonical/ubuntu-drivers-common/issues/106
            result = subprocess.check_output(cmd.split(), text=True)

        except subprocess.CalledProcessError as err:
            logger.error("Failed to install the NVIDIA driver: %s", err)
            raise err

        if "No drivers found for installation" in result:
            logger.warning(
                "No drivers for the NVIDIA GPU were found. Manual installation is necessary"
            )
            raise ResourceInstallationError(self._name)

        logger.info("NVIDIA driver installed")

    def _install_nvidia_utils(self) -> None:
        """Install the nvidia utils to be able to use nvidia-smi."""
        if not self.installed_pkgs.exists():
            logger.debug("Drivers not installed by the charm. Skipping nvidia-utils")
            return

        installed_pkgs = self.installed_pkgs.read_text(encoding="utf-8").splitlines()
        for line in installed_pkgs:
            if match := re.search(self.pkg_pattern, line):
                nvidia_version = match.group(1)
                logger.debug("installed driver from hardware-observer: %s", line)
                pkg = f"nvidia-utils-{nvidia_version}-server"
                apt.add_package(pkg, update_cache=True)
                logger.info("installed %s", pkg)
                break
        else:
            logger.warning(
                "packages installed at %s are in an unexpected format. "
                "nvidia-utils was not installed",
                self.installed_pkgs,
            )

    def remove(self) -> None:
        """Drivers shouldn't be removed by the strategy."""
        return None

    def check(self) -> bool:
        """Check if nvidia-smi is working."""
        try:
            subprocess.check_call("nvidia-smi", timeout=60)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logger.error(e)
            logger.warning(
                "nvidia-smi is not working. Ensure the correct driver is installed. "
                "See the docs for more details: "
                "https://ubuntu.com/server/docs/nvidia-drivers-installation"
            )
            return False


class SmartCtlExporterStrategy(SnapStrategy):
    """SmartCtl strategy class."""

    _name = HWTool.SMARTCTL_EXPORTER

    def __init__(self, channel: str) -> None:
        """Init."""
        self.channel = channel


class StorCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.STORCLI
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / HWTool.STORCLI.value

    def install(self) -> None:
        """Install storcli."""
        path = self._fetch_tool()

        if not validate_checksum(STORCLI_VERSION_INFOS, path):
            raise ResourceChecksumError
        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove storcli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)

    def check(self) -> bool:
        """Check resource status."""
        return self.symlink_bin.exists() and os.access(self.symlink_bin, os.X_OK)


class PercCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.PERCCLI
    origin_path = Path("/opt/MegaRAID/perccli/perccli64")
    symlink_bin = TOOLS_DIR / HWTool.PERCCLI.value

    def install(self) -> None:
        """Install perccli."""
        path = self._fetch_tool()
        if not validate_checksum(PERCCLI_VERSION_INFOS, path):
            raise ResourceChecksumError
        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove perccli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)

    def check(self) -> bool:
        """Check resource status."""
        return self.symlink_bin.exists() and os.access(self.symlink_bin, os.X_OK)


class SAS2IRCUStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.SAS2IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS2IRCU.value

    def install(self) -> None:
        """Install sas2ircu."""
        path = self._fetch_tool()
        if not validate_checksum(SAS2IRCU_VERSION_INFOS, path):
            raise ResourceChecksumError
        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove sas2ircu."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)

    def check(self) -> bool:
        """Check resource status."""
        return self.symlink_bin.exists() and os.access(self.symlink_bin, os.X_OK)


class SAS3IRCUStrategy(SAS2IRCUStrategy):
    """Strategy to install storcli."""

    _name = HWTool.SAS3IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS3IRCU.value

    def install(self) -> None:
        """Install sas3ircu."""
        path = self._fetch_tool()
        if not validate_checksum(SAS3IRCU_VERSION_INFOS, path):
            raise ResourceChecksumError
        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)


class SSACLIStrategy(StrategyABC):
    """Strategy for install ssacli."""

    _name = HWTool.SSACLI
    pkg = HWTool.SSACLI.value
    repo_line = "deb http://downloads.linux.hpe.com/SDR/repo/mcp stretch/current non-free"

    @property
    def repo(self) -> apt.DebianRepository:
        """Third party DebianRepository."""
        return apt.DebianRepository.from_repo_line(self.repo_line)

    def add_repo(self) -> None:
        """Add repository."""
        repositories = apt.RepositoryMapping()
        repositories.add(self.repo)

    def install(self) -> None:
        for key in HP_KEYS:
            apt.import_key(key)
        self.add_repo()
        apt.add_package(self.pkg, update_cache=True)

    def remove(self) -> None:
        # Skip removing because this may cause dependency error
        # for other services on the same machine.
        logger.info("SSACLIStrategy skip removing %s", self.pkg)

    def check(self) -> bool:
        """Check package status."""
        return check_deb_pkg_installed(self.pkg)


class IPMIStrategy(StrategyABC):
    """Strategy for installing ipmi."""

    freeipmi_pkg = "freeipmi-tools"

    def install(self) -> None:
        apt_helpers.add_pkg_with_candidate_version(self.freeipmi_pkg)

    def remove(self) -> None:
        # Skip removing because this may cause dependency error
        # for other services on the same machine.
        logger.info("%s skip removing %s", self._name, self.freeipmi_pkg)

    def check(self) -> bool:
        """Check package status."""
        return check_deb_pkg_installed(self.freeipmi_pkg)


class IPMISENSORStrategy(IPMIStrategy):
    """Strategy for installing ipmi."""

    _name = HWTool.IPMI_SENSOR


class IPMISELStrategy(IPMIStrategy):
    """Strategy for installing ipmi.

    The ipmiseld daemon polls the system event log (SEL)
    of specified hosts and stores the logs into the local syslog.

    Grafana agent will then forward the logs to Loki.
    """

    _name = HWTool.IPMI_SEL

    ipmiseld_pkg = "freeipmi-ipmiseld"

    def install(self) -> None:
        super().install()
        apt_helpers.add_pkg_with_candidate_version(self.ipmiseld_pkg)

    def remove(self) -> None:
        # Skip removing because this may cause dependency error
        # for other services on the same machine.
        super().remove()
        logger.info("%s skip removing %s", self._name, self.ipmiseld_pkg)

    def check(self) -> bool:
        """Check package status."""
        parent_pkg_installed = super().check()
        child_pkg_installed = check_deb_pkg_installed(self.ipmiseld_pkg)
        return parent_pkg_installed and child_pkg_installed


class IPMIDCMIStrategy(IPMIStrategy):
    """Strategy for installing ipmi."""

    _name = HWTool.IPMI_DCMI


class RedFishStrategy(StrategyABC):  # pylint: disable=R0903
    """Install strategy for redfish.

    Currently we don't do anything here.
    """

    _name = HWTool.REDFISH

    def check(self) -> bool:
        """Check package status."""
        return True


def _raid_hw_verifier_hwinfo() -> Set[HWTool]:
    """Verify if a supported RAID card exists on the machine using the hwinfo command."""
    hwinfo_output = hwinfo("storage")

    tools = set()
    for _, hwinfo_content in hwinfo_output.items():
        # ssacli
        for support_storage in HWINFO_SUPPORTED_STORAGES[HWTool.SSACLI]:
            if all(item in hwinfo_content for item in support_storage):
                tools.add(HWTool.SSACLI)
    return tools


def _raid_hw_verifier_lshw() -> Set[HWTool]:
    """Verify if a supported RAID card exists on the machine using the lshw command."""
    lshw_output = lshw()
    system_vendor = lshw_output.get("vendor")
    lshw_storage = lshw(class_filter="storage")

    tools = set()

    for info in lshw_storage:
        _id = info.get("id")
        product = info.get("product")
        vendor = info.get("vendor")
        driver = info.get("configuration", {}).get("driver")
        if _id == "sas":
            # sas3ircu
            if (
                any(
                    _product
                    for _product in LSHW_SUPPORTED_STORAGES[HWTool.SAS3IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS3IRCU)
            # sas2ircu
            if (
                any(
                    _product
                    for _product in LSHW_SUPPORTED_STORAGES[HWTool.SAS2IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS2IRCU)

        if _id == "raid":
            # ssacli
            if system_vendor == SystemVendor.HP and any(
                _product
                for _product in LSHW_SUPPORTED_STORAGES[HWTool.SSACLI]
                if _product in product
            ):
                tools.add(HWTool.SSACLI)
            # perccli
            elif system_vendor == SystemVendor.DELL:
                tools.add(HWTool.PERCCLI)
            # storcli
            elif driver == "megaraid_sas" and vendor == StorageVendor.BROADCOM:
                tools.add(HWTool.STORCLI)
    return tools


def raid_hw_verifier() -> Set[HWTool]:
    """Verify if the HWTool support RAID card exists on machine."""
    lshw_tools = _raid_hw_verifier_lshw()
    hwinfo_tools = _raid_hw_verifier_hwinfo()
    return lshw_tools | hwinfo_tools


def redfish_available() -> bool:
    """Check if redfish service is available."""
    bmc_address = get_bmc_address()
    health_check_endpoint = f"https://{bmc_address}:443/redfish/v1/"
    try:
        response = requests.get(
            health_check_endpoint, verify=False, timeout=HARDWARE_EXPORTER_SETTINGS.redfish_timeout
        )
        response.raise_for_status()
        data = response.json()
        # only check if the data is empty dict or not
        if not data:
            raise ValueError("Invalid response")
    except requests.exceptions.HTTPError as e:
        result = False
        logger.error("cannot connect to redfish: %s", str(e))
    except requests.exceptions.Timeout as e:
        result = False
        logger.error("timed out connecting to redfish: %s", str(e))
    except Exception as e:  # pylint: disable=W0718
        result = False
        logger.error("unexpected error occurs when connecting to redfish: %s", str(e))
    else:
        result = True
    return result


def bmc_hw_verifier() -> Set[HWTool]:
    """Verify if the ipmi is available on the machine.

    Using freeipmi-tools to verify, the package will be removed in removing stage.
    """
    tools = set()

    # Check if ipmi services are available
    apt_helpers.add_pkg_with_candidate_version("freeipmi-tools")

    try:
        subprocess.check_output("ipmimonitoring --sdr-cache-recreate".split())
        tools.add(HWTool.IPMI_SENSOR)
    except subprocess.CalledProcessError:
        logger.info("IPMI sensors monitoring is not available")

    try:
        subprocess.check_output("ipmi-sel --sdr-cache-recreate".split())
        tools.add(HWTool.IPMI_SEL)
    except subprocess.CalledProcessError:
        logger.info("IPMI SEL monitoring is not available")

    try:
        subprocess.check_output("ipmi-dcmi --get-system-power-statistics".split())
        tools.add(HWTool.IPMI_DCMI)
    except subprocess.CalledProcessError:
        logger.info("IPMI DCMI monitoring is not available")

    # Check if RedFish is available
    if redfish_available():
        tools.add(HWTool.REDFISH)
    else:
        logger.info("Redfish is not available")
    return tools


def disk_hw_verifier() -> Set[HWTool]:
    """Verify if the disk exists on the machine."""
    return {HWTool.SMARTCTL_EXPORTER} if lshw(class_filter="disk") else set()


def nvidia_gpu_verifier() -> Set[HWTool]:
    """Verify if the hardware has NVIDIA gpu."""
    gpus = lshw(class_filter="display")
    return {HWTool.DCGM for gpu in gpus if "nvidia" in gpu.get("vendor", "").lower()}


def detect_available_tools() -> Set[HWTool]:
    """Return HWTool detected after checking the hardware."""
    return raid_hw_verifier() | bmc_hw_verifier() | disk_hw_verifier() | nvidia_gpu_verifier()


def remove_legacy_smartctl_exporter() -> None:
    """Remove any legacy tool from older revision.

    Workaround for migrating legacy smartctl exporter to snap package.
    """
    name = "smartctl-exporter"
    smartctl_exporter = Path("opt/SmartCtlExporter/")
    smartctl_exporter_config_path = Path(f"/etc/{name}-config.yaml")
    smartctl_exporter_service_path = Path(f"/etc/systemd/system/{name}.service")
    if smartctl_exporter_service_path.exists():
        systemd.service_stop(name)
        systemd.service_disable(name)
        smartctl_exporter_service_path.unlink()
    if smartctl_exporter_config_path.exists():
        smartctl_exporter_config_path.unlink()
    if smartctl_exporter.exists():
        shutil.rmtree("/opt/SmartCtlExporter/")
