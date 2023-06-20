"""Helper for vendoer's tools."""
import logging
import shutil
import subprocess
import typing as t
from abc import ABCMeta, abstractmethod
from pathlib import Path

from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

from config import SNAP_COMMON, TOOLS_DIR, VENDOR_TOOLS

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


class VendorStrategyABC(metaclass=ABCMeta):
    """Basic install strategy class."""

    @abstractmethod
    def install(self, name: str, path: Path) -> None:
        """Installation details."""

    @abstractmethod
    def remove(self) -> None:
        """Installation details."""


class StorCLIStrategy(VendorStrategyABC):
    """Strategy to install storcli."""

    name = "storcli"
    origin_path = Path("/opt/MegaRAID/storcli/storcli64")
    symlink_bin = TOOLS_DIR / "storcli"

    def install(self, name: str, path: Path) -> None:
        """Install storecli."""
        install_deb(name, path)
        symlink(src=self.origin_path, dst=self.symlink_bin)

    def remove(self) -> None:
        """Remove storecli."""
        self.symlink_bin.unlink(missing_ok=True)
        logger.debug("Remove file %s", self.symlink_bin)
        remove_deb(pkg=self.name)


class VendorHelper:
    """Helper to install vendor's tools."""

    @property
    def strategies(self) -> t.Dict[str, VendorStrategyABC]:
        """Define strategies for every vendor's tools."""
        return {
            "storecli-deb": StorCLIStrategy(),
        }

    def fetch_tools(self, resources: Resources) -> t.List[str]:
        """Fetch resource from juju if it's VENDOR_TOOLS."""
        # Fetch all tools from juju resources
        for tool in VENDOR_TOOLS:
            try:
                resources.fetch(tool)
            except ModelError:
                logger.warning("Fail to fetch tool: %s", tool)

        fetch_tools = [
            name
            for name, path in resources._paths.items()  # pylint: disable=W0212
            if name in VENDOR_TOOLS and path is not None
        ]
        return fetch_tools

    def install(self, resources: Resources) -> None:
        """Install tools."""
        fetch_tools = self.fetch_tools(resources)
        for name, path in resources._paths.items():  # pylint: disable=W0212
            if name in fetch_tools:
                strategy = self.strategies.get(name)
                if strategy and path:
                    strategy.install(name, path)
                else:
                    logger.warning("Could not find install strategy for tool %s", name)

    def remove(self, resources: Resources) -> None:
        """Execute all remove strategies."""
        for name in resources._paths.keys():  # pylint: disable=W0212
            if name in VENDOR_TOOLS:
                strategy = self.strategies.get(name)
                if strategy:
                    strategy.remove()
                    logger.info("Remove resource: %s", name)
                else:
                    logger.warning("Could not find remove strategy for tool %s", name)
