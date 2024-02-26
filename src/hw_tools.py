"""Helper for hardware tools.

Define strategy for install, remove and verifier for different hardwares.
"""

import logging
import os
import shutil
import stat
import subprocess
from abc import ABCMeta, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple

from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources
from redfish import redfish_client
from redfish.rest.v1 import (
    InvalidCredentialsError,
    RetriesExhaustedError,
    ServerDownOrUnreachableError,
    SessionCreationError,
)

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
    REDFISH_MAX_RETRY,
    REDFISH_TIMEOUT,
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


class ResourceFileSizeZeroError(Exception):
    """Empty resource error."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"Tool: {tool} path: {path} size is zero"


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
        # Skip removing because we afriad this cause dependency error
        # for other services on the same machine.
        logger.info("SSACLIStrategy skip removing %s", self.pkg)

    def check(self) -> bool:
        """Check package status."""
        return check_deb_pkg_installed(self.pkg)


class IPMIStrategy(APTStrategyABC):
    """Strategy for installing ipmi."""

    # Because IPMISTrategy now encompasses all of
    # HWTool.IPMI_SENSOR, HWTool.IPMI_SEL and HWTool.IPMI_DCMI,
    # we will need some refactoring here to avoid misleading log
    # messages. The installation should be good since all of these
    # tools require the same `freeipmi-tools` to be installed.
    _name = HWTool.IPMI_SENSOR
    pkg = "freeipmi-tools"

    def install(self) -> None:
        apt_helpers.add_pkg_with_candidate_version(self.pkg)

    def remove(self) -> None:
        # Skip removing because we afriad this cause dependency error
        # for other services on the same machine.
        logger.info("IPMIStrategy skip removing %s", self.pkg)

    def check(self) -> bool:
        """Check package status."""
        return check_deb_pkg_installed(self.pkg)


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


# Using cache here to avoid repeat call.
# The lru_cache should be clean everytime the hook been triggered.
@lru_cache
def raid_hw_verifier() -> List[HWTool]:
    """Verify if the HWTool support RAID card exists on machine."""
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

    hwinfo_tools = _raid_hw_verifier_hwinfo()
    return list(tools | hwinfo_tools)


# Using cache here to avoid repeat call.
# The lru_cache should be clean everytime the hook been triggered.
@lru_cache
def redfish_available() -> bool:
    """Check if redfish service is available."""
    bmc_address = get_bmc_address()
    host = f"https://{bmc_address}"
    try:
        # credentials can be empty because we're only checking if redfish service is accessible
        redfish_obj = redfish_client(
            base_url=host,
            username="",
            password="",
            timeout=REDFISH_TIMEOUT,
            max_retry=REDFISH_MAX_RETRY,
        )
        redfish_obj.login(auth="session")
    except (RetriesExhaustedError, ServerDownOrUnreachableError):
        # redfish not available
        result = False
    except (SessionCreationError, InvalidCredentialsError):
        # redfish available, wrong credentials or not able to create a session
        result = True
    except Exception as e:  # pylint: disable=W0718
        # mark redfish unavailable for any generic exception
        result = False
        logger.error("cannot connect to redfish: %s", str(e))
    else:  # login succeeded with empty credentials
        result = True
        redfish_obj.logout()

    return result


# Using cache here to avoid repeat call.
# The lru_cache should be clean everytime the hook been triggered.
@lru_cache
def bmc_hw_verifier() -> List[HWTool]:
    """Verify if the ipmi is available on the machine.

    Using freeipmi-tools to verify, the package will be removed in removing stage.
    """
    tools = []

    # Check if ipmi services are available
    apt_helpers.add_pkg_with_candidate_version("freeipmi-tools")

    try:
        subprocess.check_output("ipmimonitoring".split())
        tools.append(HWTool.IPMI_SENSOR)
    except subprocess.CalledProcessError:
        logger.info("IPMI sensors monitoring is not available")

    try:
        subprocess.check_output("ipmi-sel".split())
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


# Using cache here to avoid repeat call.
# The lru_cache should be clean everytime the hook been triggered.
@lru_cache
def get_hw_tool_white_list() -> List[HWTool]:
    """Return HWTool white list."""
    raid_white_list = raid_hw_verifier()
    bmc_white_list = bmc_hw_verifier()
    return raid_white_list + bmc_white_list


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
            IPMIStrategy(),
            RedFishStrategy(),
        ]

    def fetch_tools(  # pylint: disable=W0102
        self,
        resources: Resources,
        hw_white_list: List[HWTool] = [],
    ) -> Dict[HWTool, Path]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        fetch_tools: Dict[HWTool, Path] = {}
        # Fetch all tools from juju resources
        for tool, resource in TPR_RESOURCES.items():
            if tool not in hw_white_list:
                logger.info("Skip fetch tool: %s", tool)
                continue
            try:
                path = resources.fetch(resource)
                fetch_tools[tool] = path
            except ModelError:
                logger.warning("Fail to fetch tool: %s", resource)

        return fetch_tools

    def check_missing_resources(
        self, hw_white_list: List[HWTool], fetch_tools: Dict[HWTool, Path]
    ) -> Tuple[bool, str]:
        """Check if required resources are not been uploaded."""
        missing_resources = []
        for tool in hw_white_list:
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

    def install(self, resources: Resources) -> Tuple[bool, str]:
        """Install tools."""
        hw_white_list: List[HWTool] = get_hw_tool_white_list()
        logger.info("hw_tool_white_list: %s", hw_white_list)

        fetch_tools: Dict[HWTool, Path] = self.fetch_tools(resources, hw_white_list)

        ok, msg = self.check_missing_resources(hw_white_list, fetch_tools)
        if not ok:
            return ok, msg

        fail_strategies = []

        # Iterate over each strategy and execute.
        for strategy in self.strategies:
            if strategy.name not in hw_white_list:
                continue
            # TPRStrategy
            try:
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

    def remove(self, resources: Resources) -> None:  # pylint: disable=W0613
        """Execute all remove strategies."""
        hw_white_list: List[HWTool] = get_hw_tool_white_list()
        for strategy in self.strategies:
            if strategy.name not in hw_white_list:
                continue
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Strategy %s remove success", strategy)

    def check_installed(self) -> Tuple[bool, str]:
        """Check tool status."""
        hw_white_list: List[HWTool] = get_hw_tool_white_list()
        failed_checks: List[HWTool] = []

        for strategy in self.strategies:
            if strategy.name not in hw_white_list:
                continue
            ok = strategy.check()
            if not ok:
                failed_checks.append(strategy.name)

        if failed_checks:
            return False, f"Fail strategy checks: {failed_checks}"
        return True, ""
