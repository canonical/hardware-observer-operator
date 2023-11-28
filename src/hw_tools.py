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
from functools import cached_property
from pathlib import Path

from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

import hw_resources
from checksum import (
    PERCCLI_VERSION_INFOS,
    SAS2IRCU_VERSION_INFOS,
    SAS3IRCU_VERSION_INFOS,
    STORCLI_VERSION_INFOS,
)
from config import EXPORTER_COLLECTOR_MAPPING, SNAP_COMMON, TOOLS_DIR, TPR_RESOURCES, HWTool
from hardware import get_hw_tool_white_list
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
    def check_status(self) -> t.Dict[str, bool]:
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

    @abstractmethod
    def validate_tool(self) -> bool:
        """Check if the tool is valid or not."""


class TPRStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Third party resource strategy class."""

    @abstractmethod
    def install(self, path: Path) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""

    @abstractmethod
    def validate_tool(self, path: Path) -> bool:
        """Check if the tool is valid or not."""


class StorCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.STORCLI
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / HWTool.STORCLI.value

    def install(self, path: Path) -> None:
        """Install storcli."""
        if not self.validate_tool(path):
            logger.error("%s is not valid.", self.name)
            return

        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove storcli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)

    def check_status(self) -> t.Dict[str, bool]:
        """Check installation status of third party tool."""
        try:
            path = self.symlink_bin
            exists = hw_resources.check_file_exists(path)
            executable = hw_resources.check_file_executable(path)
        except hw_resources.ResourceIsDirectoryError as err:
            raise err

        if not exists:
            raise hw_resources.ResourceNotFoundError(tool=self.name, path=path)
        if not executable:
            raise hw_resources.ResourceNotExecutableError(tool=self.name, path=path)
        return {str(self.name): True}

    def validate_tool(self, path: Path) -> bool:
        """Check if third party tool is valid."""
        if not hw_resources.validate_size(path):
            raise hw_resources.ResourceFileSizeZeroError(tool=self.name, path=path)
        if not hw_resources.validate_checksum(STORCLI_VERSION_INFOS, path):
            raise hw_resources.ResourceChecksumError(tool=self.name, path=path)
        return True


class PercCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.PERCCLI
    origin_path = Path("/opt/MegaRAID/perccli/perccli64")
    symlink_bin = TOOLS_DIR / HWTool.PERCCLI.value

    def install(self, path: Path) -> None:
        """Install perccli."""
        if not self.validate_tool(path):
            logger.error("%s is not valid.", self.name)
            return

        install_deb(self.name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove perccli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)

    def check_status(self) -> t.Dict[str, bool]:
        """Check installation status of third party tool."""
        try:
            path = self.symlink_bin
            exists = hw_resources.check_file_exists(path)
            executable = hw_resources.check_file_executable(path)
        except hw_resources.ResourceIsDirectoryError as err:
            raise err

        if not exists:
            raise hw_resources.ResourceNotFoundError(tool=self.name, path=path)
        if not executable:
            raise hw_resources.ResourceNotExecutableError(tool=self.name, path=path)
        return {str(self.name): True}

    def validate_tool(self, path: Path) -> bool:
        """Check if third party tool is valid."""
        if not hw_resources.validate_size(path):
            raise hw_resources.ResourceFileSizeZeroError(tool=self.name, path=path)
        if not hw_resources.validate_checksum(PERCCLI_VERSION_INFOS, path):
            raise hw_resources.ResourceChecksumError(tool=self.name, path=path)
        return True


class SAS2IRCUStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    _name = HWTool.SAS2IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS2IRCU.value

    def install(self, path: Path) -> None:
        """Install sas2ircu."""
        if not self.validate_tool(path):
            logger.error("%s is not valid.", self.name)
            return

        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove sas2ircu."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)

    def check_status(self) -> t.Dict[str, bool]:
        """Check installation status of third party tool."""
        try:
            path = self.symlink_bin
            exists = hw_resources.check_file_exists(path)
            executable = hw_resources.check_file_executable(path)
        except hw_resources.ResourceIsDirectoryError as err:
            raise err

        if not exists:
            raise hw_resources.ResourceNotFoundError(tool=self.name, path=path)
        if not executable:
            raise hw_resources.ResourceNotExecutableError(tool=self.name, path=path)
        return {str(self.name): True}

    def validate_tool(self, path: Path) -> bool:
        """Check if third party tool is valid."""
        if not hw_resources.validate_size(path):
            raise hw_resources.ResourceFileSizeZeroError(tool=self.name, path=path)
        if not hw_resources.validate_checksum(SAS2IRCU_VERSION_INFOS, path):
            raise hw_resources.ResourceChecksumError(tool=self.name, path=path)
        return True


class SAS3IRCUStrategy(SAS2IRCUStrategy):
    """Strategy to install storcli."""

    _name = HWTool.SAS3IRCU
    symlink_bin = TOOLS_DIR / HWTool.SAS3IRCU.value

    def install(self, path: Path) -> None:
        """Install sas3ircu."""
        if not self.validate_tool(path):
            logger.error("%s is not valid.", self.name)
            return

        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)

    def validate_tool(self, path: Path) -> bool:
        """Check if third party tool is valid."""
        if not hw_resources.validate_size(path):
            raise hw_resources.ResourceFileSizeZeroError(tool=self.name, path=path)
        if not hw_resources.validate_checksum(SAS3IRCU_VERSION_INFOS, path):
            raise hw_resources.ResourceChecksumError(tool=self.name, path=path)
        return True


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

    def disable_repo(self) -> None:
        """Disable the repository."""
        repositories = apt.RepositoryMapping()
        repositories.disable(self.repo)

    def install(self) -> None:
        if not self.validate_tool():
            logger.error("%s is not valid.", self.name)
            return

        for key in HP_KEYS:
            apt.import_key(key)
        self.add_repo()
        apt.add_package(self.pkg, update_cache=True)

    def remove(self) -> None:
        apt.remove_package(self.pkg)
        self.disable_repo()

    def check_status(self) -> t.Dict[str, bool]:
        """Check package status."""
        return {self.pkg: check_deb_pkg_installed(self.pkg)}

    def validate_tool(self) -> bool:
        """Check package status."""
        # Needs implementation
        return True


class IPMIStrategy(APTStrategyABC):
    """Strategy for install ipmi."""

    _name = HWTool.IPMI
    pkgs = ["freeipmi-tools"]

    def install(self) -> None:
        if not self.validate_tool():
            logger.error("%s is not valid.", self.name)
            return

        for pkg in self.pkgs:
            apt.add_package(pkg)

    def remove(self) -> None:
        for pkg in self.pkgs:
            apt.remove_package(pkg)

    def check_status(self) -> t.Dict[str, bool]:
        """Check package status."""
        result = {}
        for pkg in self.pkgs:
            result[pkg] = check_deb_pkg_installed(pkg)
        return result

    def validate_tool(self) -> bool:
        """Check package status."""
        # Needs implementation
        return True


class RedFishStrategy(StrategyABC):  # pylint: disable=R0903
    """Install strategy for redfish.

    Currently we don't do anything here.
    """

    _name = HWTool.REDFISH

    def check_status(self) -> t.Dict[str, bool]:
        """Check package status."""
        return {"redfish": True}

    def validate_tool(self) -> bool:
        """Validate if redfish tool is valid or not."""
        return True


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

    @cached_property
    def hw_tool_white_list(self) -> t.List[HWTool]:
        """Define hardware tool white list."""
        return get_hw_tool_white_list()

    @property
    def hw_collector_white_list(self) -> t.List[str]:
        """Define hardware colletor white list."""
        collectors = []
        for tool in self.hw_tool_white_list:
            collector = EXPORTER_COLLECTOR_MAPPING.get(tool)
            if collector is not None:
                collectors += collector
        return collectors

    @property
    def strategy_white_list(self) -> t.List[StrategyABC]:
        """Define strategy white list."""
        return [s for s in self.strategies if s.name in self.hw_tool_white_list]

    def get_resource_white_list(self, resources: Resources) -> t.Dict[HWTool, t.Optional[Path]]:
        """Fetch white listed tool and path pair from juju if it's VENDOR_TOOLSa."""
        resource_white_list: t.Dict[HWTool, t.Optional[Path]] = {}
        # Note: we need to loop over TRP_RESOURCES rather than hw tool
        # whitelist because some hw tools don't need to install any resources.
        for tool, resource in TPR_RESOURCES.items():
            if tool not in self.hw_collector_white_list:
                logger.warning("Skip fetching resource for tool: %s (not in white list)", tool)
                continue

            try:
                path = resources.fetch(resource)
                logger.info("Fetched resource for tool: %s", tool)
            except ModelError:
                # If path is None, this means the resource cannot be installed or it's missing.
                path = None
                logger.warning("Failed to fetch resource for tool: %s", tool)
            else:
                resource_white_list[tool] = path

        logger.info("resource_white_list: %s", resource_white_list)
        return resource_white_list

    def install(
        self,
        resource_white_list: t.Dict[HWTool, t.Optional[Path]],
        resource_black_list: t.Dict[HWTool, bool],
    ) -> t.Dict[HWTool, bool]:
        """Install tools."""
        logger.info("hw_tool_white_list: %s", self.hw_tool_white_list)
        logger.info("hw_collector_white_list: %s", self.hw_collector_white_list)

        resource_install_status = {}
        # Iterate over each white listed strategy and execute.
        for strategy in self.strategy_white_list:
            if resource_black_list.get(strategy.name, False):
                logger.info("Strategy %s already installed, skipping", strategy)
                continue

            try:
                # TPRStrategy
                if isinstance(strategy, TPRStrategyABC):
                    path = resource_white_list.get(strategy.name)
                    if path:
                        strategy.install(path)
                # APTStrategy
                elif isinstance(strategy, APTStrategyABC):
                    strategy.install()
                logger.info("Strategy %s install success", strategy)
            except (
                OSError,
                apt.PackageError,
                hw_resources.ResourceChecksumError,
                hw_resources.ResourceFileSizeZeroError,
            ) as e:
                resource_install_status[strategy.name] = False
                logger.warning("Strategy %s install fail: %s", strategy, e)
            else:
                resource_install_status[strategy.name] = True

        return resource_install_status

    def remove(self, resources: Resources) -> None:  # pylint: disable=W0613
        """Execute all remove strategies."""
        for strategy in self.strategy_white_list:
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Strategy %s remove success", strategy)

    def check_status(self) -> t.Tuple[bool, str]:
        """Check tool status."""
        failed_checks = []

        for strategy in self.strategy_white_list:
            try:
                result = strategy.check_status()
            except (
                hw_resources.ResourceNotFoundError,
                hw_resources.ResourceIsDirectoryError,
                hw_resources.ResourceNotExecutableError,
            ) as e:
                failed_checks.append(strategy.name)
                logger.error("Strategy %s check status failed: %s", strategy.name, e)
            else:
                for name, status in result.items():
                    if not status:
                        logger.error(
                            "Strategy %s check status failed: %s not installed", strategy, name
                        )
                if not all(result.values()):
                    failed_checks.append(strategy.name)

        if len(failed_checks) > 0:
            return (
                False,
                f"Fail strategy checks: {failed_checks}, please refer to juju debug-log.",
            )
        return True, ""
