"""Helper for vendoer's tools."""
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

from config import SNAP_COMMON, TOOLS_DIR, TPR_VENDOR_TOOLS, VENDOR_TOOLS
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
    def install(self, name: str, path: Path) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Remove details."""


class StorCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    name = "storcli"
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / "storcli"

    def install(self, name: str, path: Path) -> None:
        """Install storcli."""
        install_deb(name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove storcli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)


class PercCLIStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    name = "perccli"
    origin_path = Path("/opt/MegaRAID/perccli/perccli64")
    symlink_bin = TOOLS_DIR / "perccli"

    def install(self, name: str, path: Path) -> None:
        """Install perccli."""
        install_deb(name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove perccli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)


class SAS2IRCUStrategy(TPRStrategyABC):
    """Strategy to install storcli."""

    name = "sas2ircu"
    symlink_bin = TOOLS_DIR / "sas2ircu"

    def install(self, name: str, path: Path) -> None:
        """Install sas2ircu."""
        make_executable(path)
        symlink(src=path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove sas2ircu."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)


class SAS3IRCUStrategy(SAS2IRCUStrategy):
    """Strategy to install storcli."""

    name = "sas3ircu"
    symlink_bin = TOOLS_DIR / "sas3ircu"


class SSACLIStrategy(APTStrategyABC):
    """Strategy for install ssacli."""

    name = "ssacli"
    pkg = "ssacli"
    repo_line = "deb http://downloads.linux.hpe.com/SDR/repo/mcp stretch/current non-free"

    @property
    def repo(self) -> apt.DebianRepository:
        """Third party DebianRepository."""
        return apt.DebianRepository.from_repo_line(self.repo_line)

    def add_repo(self) -> None:
        """Add repository."""
        repositories = apt.RepositoryMapping()
        print(repositories)
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


class VendorHelper:
    """Helper to install vendor's tools."""

    @property
    def strategies(self) -> t.Dict[str, StrategyABC]:
        """Define strategies for every vendor's tools."""
        return {
            "storcli-deb": StorCLIStrategy(),
            "perccli-deb": PercCLIStrategy(),
            "sas2ircu-bin": SAS2IRCUStrategy(),
            "sas3ircu-bin": SAS3IRCUStrategy(),
            "ssacli": SSACLIStrategy(),
        }

    def fetch_tools(self, resources: Resources) -> t.Dict[str, Path]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        fetch_tools: t.Dict[str, Path] = {}
        # Fetch all tools from juju resources
        for tool in TPR_VENDOR_TOOLS:
            try:
                path = resources.fetch(tool)
                fetch_tools[tool] = path
            except ModelError:
                logger.warning("Fail to fetch tool: %s", tool)

        return fetch_tools

    def install(self, resources: Resources) -> None:
        """Install tools."""
        fetch_tools = self.fetch_tools(resources)
        for name in VENDOR_TOOLS:
            strategy = self.strategies.get(name)
            if strategy is None:
                logger.warning("Could not find install strategy for tool %s", name)
            # TPRStrategy
            if name in fetch_tools and isinstance(strategy, TPRStrategyABC):
                path = resources._paths.get(name)  # pylint: disable=W0212
                if path:
                    strategy.install(name, path)
            # APTStrategy
            if isinstance(strategy, APTStrategyABC):
                strategy.install()

    def remove(self, resources: Resources) -> None:  # pylint: disable=W0613
        """Execute all remove strategies."""
        for name in VENDOR_TOOLS:
            strategy = self.strategies.get(name)
            if not strategy:
                logger.warning("Could not find remove strategy for tool %s", name)
                continue
            if isinstance(strategy, (TPRStrategyABC, APTStrategyABC)):
                strategy.remove()
            logger.info("Remove resource: %s", name)
