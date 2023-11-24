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

from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

import hw_resources
from checksum import (
    PERCCLI_VERSION_INFOS,
    SAS2IRCU_VERSION_INFOS,
    SAS3IRCU_VERSION_INFOS,
    STORCLI_VERSION_INFOS,
    ToolVersionInfo,
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
    def check_status(self) -> bool:
        """Check installation status of the tool."""


class APTStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Abstract strategy for apt install tool."""

    apt_keys: t.List
    package_source_mapping = t.Dict[str, str]

    @abstractmethod
    def add_repos(self) -> None:
        """Add apt repositories."""

    @abstractmethod
    def disable_repos(self) -> None:
        """Disable apt repositories."""

    @abstractmethod
    def install(self) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""

    @abstractmethod
    def validate_tool(self) -> bool:
        """Check if the tool is valid or not."""


class APTStrategy(APTStrategyABC):
    """Strategy for apt install tool."""

    apt_keys = []
    package_source_mapping: t.Dict[str, str] = {}

    @property
    def repos(self) -> t.List[apt.DebianRepository]:
        """Third party DebianRepositories."""
        repos = []
        for repo_line in self.package_source_mapping.values():
            if not repo_line:
                repos.append(apt.DebianRepository.from_repo_line(repo_line))
        return repos

    def add_repos(self) -> None:
        """Add apt repositories."""
        repositories = apt.RepositoryMapping()
        for repo in self.repos:
            repositories.add(repo)

    def disable_repos(self) -> None:
        """Disable apt repositories."""
        repositories = apt.RepositoryMapping()
        for repo in self.repos:
            repositories.disable(repo)

    def install(self) -> None:
        """Install apt packages."""
        if not self.validate_tool():
            logger.error("%s is not valid.", self.name)
            return

        for key in self.apt_keys:
            apt.import_key(key)
        self.add_repos()
        for package in self.package_source_mapping:
            apt.add_package(package, update_cache=True)

    def remove(self) -> None:
        """Remove apt packages."""
        # Note: The repo and keys should be remove when removing
        # hook is triggered. But currently the apt lib don't have
        # the remove option.
        for package in self.package_source_mapping:
            apt.remove_package(package)
        self.disable_repos()

    def check_status(self) -> bool:
        """Check package status."""
        success = True
        for package in self.package_source_mapping:
            success &= check_deb_pkg_installed(package)
        return success

    def validate_tool(self) -> bool:
        """Check package status."""
        # Needs implementation
        return True


class TPRStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Third party resource strategy abstract class."""

    origin_path: Path
    symlink_bin: Path
    is_debian_package: bool
    version_infos: t.List[ToolVersionInfo]

    @abstractmethod
    def install(self, path: Path) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""

    @abstractmethod
    def check_status(self) -> bool:
        """Check installation status of the tool."""

    @abstractmethod
    def validate_tool(self, path: Path) -> bool:
        """Check if the tool is valid or not."""


class TPRStrategy(TPRStrategyABC):
    """Third party resource strategy base class."""

    origin_path = Path("")
    symlink_bin = Path("")
    is_debian_package = False
    version_infos = []

    def install(self, path: Path) -> None:
        """Install third party tool."""
        if not self.validate_tool(path):
            logger.error("%s is not valid.", self.name)
            return

        if self.is_debian_package:
            install_deb(self.name, path)
            if self.origin_path != Path(""):
                symlink(src=self.origin_path, dst=self.symlink_bin)
        else:
            make_executable(path)
            symlink(src=path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove third party tool."""
        logger.debug("Remove file %s", self.symlink_bin)
        self.symlink_bin.unlink(missing_ok=True)
        if self.is_debian_package:
            remove_deb(pkg=self.name)

    def check_status(self) -> bool:
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
        return True

    def validate_tool(self, path: Path) -> bool:
        """Check if third party tool is valid."""
        if not hw_resources.validate_size(path):
            raise hw_resources.ResourceFileSizeZeroError(tool=self.name, path=path)
        if not hw_resources.validate_checksum(self.version_infos, path):
            raise hw_resources.ResourceChecksumError(tool=self.name, path=path)
        return True


class StorCLIStrategy(TPRStrategy):
    """Strategy to install storcli."""

    _name = HWTool.STORCLI
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / HWTool.STORCLI.value
    is_debian_package = True
    version_infos = STORCLI_VERSION_INFOS


class PercCLIStrategy(TPRStrategy):
    """Strategy to install storcli."""

    _name = HWTool.PERCCLI
    origin_path = Path("/opt/MegaRAID/perccli/perccli64")
    symlink_bin = TOOLS_DIR / HWTool.PERCCLI.value
    is_debian_package = True
    version_infos = PERCCLI_VERSION_INFOS


class SAS2IRCUStrategy(TPRStrategy):
    """Strategy to install storcli."""

    _name = HWTool.SAS2IRCU
    origin_path = Path("")
    symlink_bin = TOOLS_DIR / HWTool.SAS2IRCU.value
    is_debian_package = False
    version_infos = SAS2IRCU_VERSION_INFOS


class SAS3IRCUStrategy(TPRStrategy):
    """Strategy to install storcli."""

    _name = HWTool.SAS3IRCU
    origin_path = Path("")
    symlink_bin = TOOLS_DIR / HWTool.SAS3IRCU.value
    is_debian_package = False
    version_infos = SAS3IRCU_VERSION_INFOS


class SSACLIStrategy(APTStrategy):
    """Strategy for install ssacli."""

    _name = HWTool.SSACLI
    apt_keys = HP_KEYS
    package_source_mapping = {
        HWTool.SSACLI.value: (
            "deb http://downloads.linux.hpe.com/SDR/repo/mcp stretch/current non-free"
        )
    }


class IPMIStrategy(APTStrategy):
    """Strategy for install ipmi."""

    _name = HWTool.IPMI
    apt_keys = []
    package_source_mapping = {"freeipmi-tools": ""}


class RedFishStrategy(StrategyABC):  # pylint: disable=R0903
    """Install strategy for redfish.

    Currently we don't do anything here.
    """

    _name = HWTool.REDFISH

    def check_status(self) -> bool:
        """Check redfish status."""
        return True

    def validate_tool(self) -> bool:
        """Validate if redfish tool is valid or not."""
        return True


class HWToolHelper:
    """Helper to install vendor's or hardware related tools."""

    _hw_tool_white_list: t.Optional[t.List[HWTool]] = None
    _hw_collector_white_list: t.Optional[t.List[str]] = None
    _strategy_white_list: t.Optional[t.List[StrategyABC]] = None

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

    @property
    def hw_tool_white_list(self) -> t.List[HWTool]:
        """Define hardware tool white list."""
        # cache the white list because it might be expensive to get
        if self._hw_tool_white_list is None:
            self._hw_tool_white_list = get_hw_tool_white_list()
        return self._hw_tool_white_list

    @property
    def hw_collector_white_list(self) -> t.List[str]:
        """Define hardware colletor white list."""
        # cache the white list because it might be expensive to get
        if self._hw_collector_white_list is None:
            collectors = []
            for tool in self.hw_tool_white_list:
                collector = EXPORTER_COLLECTOR_MAPPING.get(tool)
                if collector is not None:
                    collectors += collector
            self._hw_collector_white_list = collectors
        return self._hw_collector_white_list

    @property
    def strategy_white_list(self) -> t.List[StrategyABC]:
        """Define strategy white list."""
        # cache the white list because it might be expensive to get
        if self._strategy_white_list is None:
            strategies = [s for s in self.strategies if s.name in self.hw_tool_white_list]
            self._strategy_white_list = strategies
        return self._strategy_white_list

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
        self, resource_white_list: t.Dict[HWTool, t.Optional[Path]]
    ) -> t.Dict[HWTool, bool]:
        """Install tools."""
        logger.info("hw_tool_white_list: %s", self.hw_tool_white_list)
        logger.info("hw_collector_white_list: %s", self.hw_collector_white_list)

        resource_install_status = {}
        # Iterate over each white listed strategy and execute.
        for strategy in self.strategy_white_list:
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

    def check_statuses(self) -> t.Tuple[bool, str]:
        """Check tool status."""
        failed_checks = []

        for strategy in self.strategy_white_list:
            ok = strategy.check_status()
            if not ok:
                failed_checks.append(strategy.name)

        if len(failed_checks) > 0:
            return False, f"Fail strategy checks: {failed_checks}"
        return True, ""
