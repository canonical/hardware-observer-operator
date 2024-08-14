"""Helper for hardware tools.

Define strategy for install, remove and verifier for different hardware.
"""

import io
import logging
import os
import shutil
import stat
import subprocess
import tarfile
from abc import ABCMeta, abstractmethod
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests
import urllib3
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

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


class APTStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Strategy for apt install tool."""

    @abstractmethod
    def install(self) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""
        # Note: The repo and keys should be remove when removing
        # hook is triggered. But currently the apt lib don't have
        # the remove option.


class TPRStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Third party resource strategy class."""

    @abstractmethod
    def install(self, path: Path) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""


class StorCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.STORCLI
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / HWTool.STORCLI.value

    def install(self, path: Path) -> None:
        """Install storcli."""
        if file_is_empty(path):
            logger.info("Skipping StorCLI resource install since empty file was detected.")
            raise ResourceFileSizeZeroError(tool=self._name, path=path)
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

    def install(self, path: Path) -> None:
        """Install perccli."""
        if file_is_empty(path):
            logger.info("Skipping PERCCLI resource install since empty file was detected.")
            raise ResourceFileSizeZeroError(tool=self._name, path=path)
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

    def install(self, path: Path) -> None:
        """Install sas2ircu."""
        if file_is_empty(path):
            logger.info("Skipping SAS2IRCU resource install since empty file was detected.")
            raise ResourceFileSizeZeroError(tool=self._name, path=path)
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

    def install(self, path: Path) -> None:
        """Install sas3ircu."""
        if file_is_empty(path):
            logger.info("Skipping SAS3IRCU resource install since empty file was detected.")
            raise ResourceFileSizeZeroError(tool=self._name, path=path)
        if not validate_checksum(SAS3IRCU_VERSION_INFOS, path):
            raise ResourceChecksumError
        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)


class SSACLIStrategy(APTStrategyABC):
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


class IPMIStrategy(APTStrategyABC):
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


class SmartCtlStrategy(APTStrategyABC):
    """Strategy for installing ipmi."""

    pkg = "smartmontools"
    _name = HWTool.SMARTCTL

    def install(self) -> None:
        apt_helpers.add_pkg_with_candidate_version(self.pkg)

    def remove(self) -> None:
        # Skip removing because this may cause dependency error
        # for other services on the same machine.
        logger.info("%s skip removing %s", self._name, self.pkg)

    def check(self) -> bool:
        """Check package status."""
        return check_deb_pkg_installed(self.pkg)


class SmartCtlExporterStrategy(StrategyABC):  # pylint: disable=R0903
    """Install smartctl exporter binary."""

    _name = HWTool.SMARTCTL_EXPORTER

    _resource_dir = Path("/opt/SmartCtlExporter/")
    _release = (
        "https://github.com/prometheus-community/"
        "smartctl_exporter/releases/download/v0.12.0/smartctl_exporter-0.12.0.linux-amd64.tar.gz"
    )
    _exporter_name = "smartctl_exporter"
    _exporter_path = Path(_resource_dir / "smartctl_exporter")

    def install(self) -> None:
        """Install exporter binary from internet."""
        logger.debug("Installing SmartCtlExporter")
        self._resource_dir.mkdir(parents=True, exist_ok=True)

        resp = requests.get(self._release, timeout=60)
        if resp.status_code != HTTPStatus.OK:
            logger.error("Failed to download smartctl exporter binary.")
            raise ResourceInstallationError(self._name)

        success = False
        fileobj = io.BytesIO(resp.content)
        with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(self._exporter_name):
                    with open(self._exporter_path, "wb") as outfile:
                        member_file = tar.extractfile(member)
                        if member_file:
                            outfile.write(member_file.read())
                            success = True
                    if success:
                        make_executable(self._exporter_path)
        if not success:
            logger.error("Failed to install SmartCtlExporter binary.")
            raise ResourceInstallationError(self._name)

    def remove(self) -> None:
        """Remove downloaded exporter binary."""
        logger.debug("Remove SmartCtlExporter")
        shutil.rmtree(self._resource_dir)

    def check(self) -> bool:
        """Check package status."""
        logger.debug("Check SmartCtlExporter resources")
        return self._exporter_path.is_file()


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


# Using cache here to avoid repeat call.
# The lru_cache should be cleaned every time the hook been triggered.
@lru_cache
def raid_hw_verifier() -> List[HWTool]:
    """Verify if the HWTool support RAID card exists on machine."""
    lshw_tools = _raid_hw_verifier_lshw()
    hwinfo_tools = _raid_hw_verifier_hwinfo()
    return list(lshw_tools | hwinfo_tools)


# Using cache here to avoid repeat call.
# The lru_cache should be cleaned every time the hook been triggered.
@lru_cache
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


# Using cache here to avoid repeat call.
# The lru_cache should be cleaned every time the hook been triggered.
@lru_cache
def bmc_hw_verifier() -> List[HWTool]:
    """Verify if the ipmi is available on the machine.

    Using freeipmi-tools to verify, the package will be removed in removing stage.
    """
    tools = []

    # Check if ipmi services are available
    apt_helpers.add_pkg_with_candidate_version("freeipmi-tools")

    try:
        subprocess.check_output("ipmimonitoring --sdr-cache-recreate".split())
        tools.append(HWTool.IPMI_SENSOR)
    except subprocess.CalledProcessError:
        logger.info("IPMI sensors monitoring is not available")

    try:
        subprocess.check_output("ipmi-sel --sdr-cache-recreate".split())
        tools.append(HWTool.IPMI_SEL)
    except subprocess.CalledProcessError:
        logger.info("IPMI SEL monitoring is not available")

    try:
        subprocess.check_output("ipmi-dcmi --get-system-power-statistics".split())
        tools.append(HWTool.IPMI_DCMI)
    except subprocess.CalledProcessError:
        logger.info("IPMI DCMI monitoring is not available")

    # Check if RedFish is available
    if redfish_available():
        tools.append(HWTool.REDFISH)
    else:
        logger.info("Redfish is not available")
    return tools


def disk_hw_verifier() -> List[HWTool]:
    """Verify if the disk exists on the machine."""
    lshw_storage = lshw(class_filter="disk")
    if lshw_storage:
        return [HWTool.SMARTCTL]
    return []


# Using cache here to avoid repeat call.
# The lru_cache should be cleaned every time the hook been triggered.
@lru_cache
def get_detected_hw_tools() -> List[HWTool]:
    """Return HWTool detected tools."""
    return sorted(raid_hw_verifier() + bmc_hw_verifier() + disk_hw_verifier())


class HWToolHelper:
    """Helper to install vendor's or hardware related tools."""

    @property
    def strategies(self) -> List[StrategyABC]:
        """Define strategies for every tools."""
        return [
            StorCLIStrategy(),
            PercCLIStrategy(),
            SAS2IRCUStrategy(),
            SAS3IRCUStrategy(),
            SSACLIStrategy(),
            IPMISELStrategy(),
            IPMIDCMIStrategy(),
            IPMISENSORStrategy(),
            RedFishStrategy(),
            SmartCtlStrategy(),
        ]

    def fetch_tools(  # pylint: disable=W0102
        self,
        resources: Resources,
        hw_enable_list: List[HWTool] = [],
    ) -> Dict[HWTool, Path]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        fetch_tools: Dict[HWTool, Path] = {}
        # Fetch all tools from juju resources
        for tool, resource in TPR_RESOURCES.items():
            if tool not in hw_enable_list:
                logger.info("Skip fetch tool: %s", tool)
                continue
            try:
                path = resources.fetch(resource)
                fetch_tools[tool] = path
            except ModelError:
                logger.warning("Fail to fetch tool: %s", resource)

        return fetch_tools

    def check_missing_resources(
        self, hw_enable_list: List[HWTool], fetch_tools: Dict[HWTool, Path]
    ) -> Tuple[bool, str]:
        """Check if required resources are not been uploaded."""
        missing_resources = []
        for tool in hw_enable_list:
            if tool in TPR_RESOURCES:
                # Resource hasn't been uploaded
                if tool not in fetch_tools:
                    missing_resources.append(TPR_RESOURCES[tool])
                # Uploaded but file size is zero
                path = fetch_tools.get(tool)
                if path and file_is_empty(path):
                    logger.warning(
                        "Empty resource file detected for tool %s at path %s", tool, path
                    )
                    missing_resources.append(TPR_RESOURCES[tool])
        if missing_resources:
            return False, f"Missing resources: {missing_resources}"
        return True, ""

    def install(self, resources: Resources, hw_enable_list: List[HWTool]) -> Tuple[bool, str]:
        """Install tools."""
        logger.info("hw_enable_list: %s", hw_enable_list)

        fetch_tools: Dict[HWTool, Path] = self.fetch_tools(resources, hw_enable_list)

        ok, msg = self.check_missing_resources(hw_enable_list, fetch_tools)
        if not ok:
            return ok, msg

        fail_strategies = []

        # Iterate over each strategy and execute.
        for strategy in self.strategies:
            if strategy.name not in hw_enable_list:
                continue
            try:
                # TPRStrategy
                if isinstance(strategy, TPRStrategyABC):
                    path = fetch_tools.get(strategy.name)  # pylint: disable=W0212
                    if path:
                        strategy.install(path)
                # APTStrategy
                elif isinstance(strategy, APTStrategyABC):
                    strategy.install()  # pylint: disable=E1120
                logger.info("Strategy %s install success", strategy)
            except (
                ResourceFileSizeZeroError,
                OSError,
                apt.PackageError,
                ResourceChecksumError,
            ) as e:
                logger.warning("Strategy %s install fail: %s", strategy, e)
                fail_strategies.append(strategy.name)

        if fail_strategies:
            return False, f"Fail strategies: {fail_strategies}"
        return True, ""

    # pylint: disable=W0613
    def remove(self, resources: Resources, hw_enable_list: List[HWTool]) -> None:
        """Execute all remove strategies."""
        for strategy in self.strategies:
            if strategy.name not in hw_enable_list:
                continue
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Strategy %s remove success", strategy)

    def check_installed(self, hw_enable_list: List[HWTool]) -> Tuple[bool, str]:
        """Check tool status."""
        failed_checks: List[HWTool] = []

        for strategy in self.strategies:
            if strategy.name not in hw_enable_list:
                continue
            ok = strategy.check()
            if not ok:
                failed_checks.append(strategy.name)

        if failed_checks:
            return False, f"Fail strategy checks: {failed_checks}"
        return True, ""
