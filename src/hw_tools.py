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

    @abstractmethod
    def validate_tool(self, path: Path) -> bool:
        """Check if the tool is valid or not."""


class APTStrategyABC(StrategyABC, metaclass=ABCMeta):
    """Abstract strategy for apt install tool."""

    apt_keys: t.List
    package_source_mapping = t.Dict[str, str]

    @abstractmethod
    def install(self) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""
        # Note: The repo and keys should be remove when removing
        # hook is triggered. But currently the apt lib don't have
        # the remove option.


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
        """Disable the repository."""
        repositories = apt.RepositoryMapping()
        for repo in self.repos:
            repositories.disable(repo)

    def install(self) -> None:
        for key in self.apt_keys:
            apt.import_key(key)
        self.add_repos()
        for package in self.package_source_mapping:
            apt.add_package(package, update_cache=True)

    def remove(self) -> None:
        for package in self.package_source_mapping:
            apt.remove_package(package)
        self.disable_repos()

    def check_status(self) -> bool:
        """Check package status."""
        success = True
        for package in self.package_source_mapping:
            success &= check_deb_pkg_installed(package)
        return success

    def validate_tool(self, path: Path) -> bool:
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


class TPRStrategy(TPRStrategyABC):
    """Third party resource strategy base class."""

    origin_path = Path("")
    symlink_bin = Path("")
    is_debian_package = False
    version_infos = []

    def install(self, path: Path) -> None:
        """Install third party tool."""
        if not self.validate_tool(path):
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

    def validate_tool(self, path: Path) -> bool:
        """Validate if redfish tool is valid or not."""
        return True


class HWToolHelper:
    """Helper to install vendor's or hardware related tools."""

    _hw_tool_white_list: t.Optional[t.List[HWTool]] = None
    _hw_collector_white_list: t.Optional[t.List[str]] = None

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

    def fetch_tools(self, resources: Resources) -> t.Dict[HWTool, Path]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        fetch_tools: t.Dict[HWTool, Path] = {}
        # Fetch all tools from juju resources
        for tool, resource in TPR_RESOURCES.items():
            if tool not in self.hw_tool_white_list:
                logger.info("Skip fetch tool: %s", tool)
                continue
            try:
                path = resources.fetch(resource)
                fetch_tools[tool] = path
            except ModelError:
                logger.warning("Fail to fetch tool: %s", resource)

        return fetch_tools

    def check_missing_resources(self, fetch_tools: t.Dict[HWTool, Path]) -> t.Tuple[bool, str]:
        """Check if required resources are not been uploaded."""
        missing_resources = []
        for tool in self.hw_tool_white_list:
            if tool in TPR_RESOURCES:
                # Resource hasn't been uploaded
                if tool not in fetch_tools:
                    missing_resources.append(TPR_RESOURCES[tool])
                # Uploaded but file size is zero
                path = fetch_tools.get(tool)
                if path and not hw_resources.validate_size(path):
                    logger.warning("Tool: %s path: %s size is zero", tool, path)
                    missing_resources.append(TPR_RESOURCES[tool])
        if len(missing_resources) > 0:
            return False, f"Missing resources: {missing_resources}"
        return True, ""

    def install(self, resources: Resources) -> t.Tuple[bool, str]:
        """Install tools."""
        logger.info("hw_tool_white_list: %s", self.hw_tool_white_list)

        fetch_tools = self.fetch_tools(resources)

        ok, msg = self.check_missing_resources(fetch_tools)
        if not ok:
            return ok, msg

        fail_strategies = []
        strategy_errors = []

        # Iterate over each strategy and execute.
        for strategy in self.strategies:
            if strategy.name not in self.hw_tool_white_list:
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
                OSError,
                apt.PackageError,
                hw_resources.ResourceChecksumError,
                hw_resources.ResourceFileSizeZeroError,
            ) as e:
                logger.warning("Strategy %s install fail: %s", strategy, e)
                fail_strategies.append(strategy.name)
                strategy_errors.append(e)

        if len(strategy_errors) > 0:
            return False, f"Fail strategies: {fail_strategies}"
        return True, ""

    def remove(self, resources: Resources) -> None:  # pylint: disable=W0613
        """Execute all remove strategies."""
        for strategy in self.strategies:
            if strategy.name not in self.hw_tool_white_list:
                continue
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Strategy %s remove success", strategy)

    def check(self) -> t.Tuple[bool, str]:
        """Check tool status."""
        failed_checks = []

        for strategy in self.strategies:
            if strategy.name not in self.hw_tool_white_list:
                continue
            ok = strategy.check_status()
            if not ok:
                failed_checks.append(strategy.name)

        if len(failed_checks) > 0:
            return False, f"Fail strategy checks: {failed_checks}"
        return True, ""
