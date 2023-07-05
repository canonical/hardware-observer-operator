"""Helper for hardware tools.

Define strategy for install, remove and verifier for different hardwares.
"""
import logging
import os
import shutil
import stat
import subprocess
import typing as t
from abc import ABCMeta, abstractmethod
from pathlib import Path

import redfish
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

from config import SNAP_COMMON, TOOLS_DIR, TPR_RESOURCES, HWTool, StorageVendor, SystemVendor
from hardware import SUPPORTED_STORAGES, lshw
from keys import HP_KEYS

logger = logging.getLogger(__name__)


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


def install_deb(name: str, path: Path) -> None:
    """Install local deb package."""
    _cmd: t.List[str] = ["dpkg", "-i", str(path)]
    try:
        result = subprocess.check_output(_cmd, universal_newlines=True)
        logger.debug(result)
        logger.info("Install deb package %s from %s success", name, path)
    except subprocess.CalledProcessError as exc:
        raise apt.PackageError(f"Fail to install deb {name} from {path}") from exc


def remove_deb(pkg: str) -> None:
    """Remove deb package."""
    _cmd: t.List[str] = ["dpkg", "--remove", pkg]
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


class StrategyABC(metaclass=ABCMeta):  # pylint: disable=R0903
    """Basic strategy."""

    _name: HWTool

    @property
    def name(self) -> HWTool:
        """Name."""
        return self._name


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

    @staticmethod
    def check_file_size(path: Path) -> bool:
        """Verify if the file size > 0.

        Because charm focus us to publish the resources on charmhub,
        but most of the hardware related tools have the un-republish
        policy. Currently our solution is publish a empty file which
        size is 0.
        """
        if path.stat().st_size == 0:
            logger.info("% size is 0, skip install", path)
            return False
        return True

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
        if not self.check_file_size(path):
            return
        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove storcli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)


class PercCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.PERCCLI
    origin_path = Path("/opt/MegaRAID/perccli/perccli64")
    symlink_bin = TOOLS_DIR / HWTool.PERCCLI.value

    def install(self, path: Path) -> None:
        """Install perccli."""
        if not self.check_file_size(path):
            return
        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove perccli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)


class SAS2IRCUStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.SAS2IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS2IRCU.value

    def install(self, path: Path) -> None:
        """Install sas2ircu."""
        if not self.check_file_size(path):
            return
        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove sas2ircu."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)


class SAS3IRCUStrategy(SAS2IRCUStrategy):
    """Strategy to install storcli."""

    _name = HWTool.SAS3IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS3IRCU.value


class SSACLIStrategy(APTStrategyABC):
    """Strategy for install ssacli."""

    _name = HWTool.SSACLI
    pkg = HWTool.SSACLI
    repo_line = "deb http://downloads.linux.hpe.com/SDR/repo/mcp stretch/current non-free"

    @property
    def repo(self) -> apt.DebianRepository:
        """Third party DebianRepository."""
        return apt.DebianRepository.from_repo_line(self.repo_line)

    def add_repo(self) -> None:
        """Add repository."""
        repositories = apt.RepositoryMapping()
        repositories.add(self.repo)

    def disable_repo(self) -> None:
        """Disable the repository."""
        repositories = apt.RepositoryMapping()
        repositories.disable(self.repo)

    def install(self) -> None:
        for key in HP_KEYS:
            apt.import_key(key)
        self.add_repo()
        apt.add_package(self.pkg, update_cache=True)

    def remove(self) -> None:
        apt.remove_package(self.pkg)
        self.disable_repo()


class IPMIStrategy(APTStrategyABC):
    """Strategy for install ipmi."""

    _name = HWTool.IPMI
    pkgs = ["freeipmi-tools"]

    def install(self) -> None:
        for pkg in self.pkgs:
            apt.add_package(pkg)

    def remove(self) -> None:
        for pkg in self.pkgs:
            apt.remove_package(pkg)


class RedFishStrategy(StrategyABC):  # pylint: disable=R0903
    """Install strategy for redfish.

    Currently we don't do anything here.
    """

    _name = HWTool.REDFISH


def raid_hw_verifier() -> t.List[HWTool]:
    """Verify if the HWTool support RAID card exists on machine."""
    hw_info = lshw()
    system_vendor = hw_info.get("vendor")
    storage_info = lshw(class_filter="storage")

    tools = set()

    for info in storage_info:
        _id = info.get("id")
        product = info.get("product")
        vendor = info.get("vendor")
        driver = info.get("configuration", {}).get("driver")
        if _id == "sas":
            # sas3ircu
            if (
                any(
                    _product
                    for _product in SUPPORTED_STORAGES[HWTool.SAS3IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS3IRCU)
            # sas2ircu
            if (
                any(
                    _product
                    for _product in SUPPORTED_STORAGES[HWTool.SAS2IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS2IRCU)

        if _id == "raid":
            # ssacli
            if system_vendor == SystemVendor.HP and any(
                _product for _product in SUPPORTED_STORAGES[HWTool.SSACLI] if _product in product
            ):
                tools.add(HWTool.SSACLI)
            # perccli
            elif system_vendor == SystemVendor.DELL:
                tools.add(HWTool.PERCCLI)
            # storcli
            elif driver == "megaraid_sas" and vendor == StorageVendor.BROADCOM:
                tools.add(HWTool.STORCLI)
    return list(tools)


def bmc_hw_verifier() -> t.List[HWTool]:
    """Verify if the ipmi is available on the machine.

    Using ipmitool to verify, the package will be removed in removing stage.
    """
    tools = []
    # Check IPMI available
    apt.add_package("ipmitool", update_cache=True)
    try:
        subprocess.check_output("ipmitool lan print".split())
        tools.append(HWTool.IPMI)
    except subprocess.CalledProcessError:
        logger.info("IPMI is not available")

    # Check RedFish available
    services = redfish.discover_ssdp()
    if len(services):
        tools.append(HWTool.REDFISH)
    else:
        logger.info("Redfish is not available")
    return tools


def get_hw_tool_white_list() -> t.List[HWTool]:
    """Return HWTool white list."""
    raid_white_list = raid_hw_verifier()
    bmc_white_list = bmc_hw_verifier()
    return raid_white_list + bmc_white_list


class HWToolHelper:
    """Helper to install vendor's or hardware related tools."""

    @property
    def strategies(self) -> t.List[StrategyABC]:
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

    def fetch_tools(self, resources: Resources) -> t.Dict[str, Path]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        fetch_tools: t.Dict[str, Path] = {}
        # Fetch all tools from juju resources
        for tool, resource in TPR_RESOURCES.items():
            try:
                path = resources.fetch(resource)
                fetch_tools[tool] = path
            except ModelError:
                logger.warning("Fail to fetch tool: %s", resource)

        return fetch_tools

    def install(self, resources: Resources) -> None:
        """Install tools."""
        self.fetch_tools(resources)
        hw_white_list = get_hw_tool_white_list()
        logger.info("hw_tool_white_list: %s", hw_white_list)
        for strategy in self.strategies:
            if strategy.name not in hw_white_list:
                continue
            # TPRStrategy
            if isinstance(strategy, TPRStrategyABC):
                resource = TPR_RESOURCES.get(strategy.name)
                if not resource:
                    continue
                path = resources._paths.get(resource)  # pylint: disable=W0212
                if path:
                    strategy.install(path)
            # APTStrategy
            elif isinstance(strategy, APTStrategyABC):
                strategy.install()  # pylint: disable=E1120

    def remove(self, resources: Resources) -> None:  # pylint: disable=W0613
        """Execute all remove strategies."""
        hw_white_list = get_hw_tool_white_list()
        for strategy in self.strategies:
            if strategy.name not in hw_white_list:
                continue
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Remove resource: %s", strategy)
