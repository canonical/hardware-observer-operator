"""Helper for vendoer's tools."""
import logging
import shutil
import subprocess
import typing as t
from abc import ABCMeta, abstractmethod
from pathlib import Path

from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError, Resources

from config import SNAP_COMMON, VENDOR_TOOLS

logger = logging.getLogger(__name__)


def copy_to_snap_common_bin(source: Path, filename: str) -> None:
    """Copy file to $SNAP_COMMON/bin folder."""
    Path(f"{SNAP_COMMON}/bin").mkdir(parents=False, exist_ok=True)
    shutil.copy(source, f"{SNAP_COMMON}/bin/{filename}")


class InstallStrategyABC(metaclass=ABCMeta):  # pylint: disable=R0903
    """Basic install strategy class."""

    @abstractmethod
    def install(self, name: str, path: Path) -> None:
        """Installation details."""


class DebInstallStrategy(InstallStrategyABC):  # pylint: disable=R0903
    """Debain package install strategy."""

    def install(self, name: str, path: Path) -> None:
        """Install local deb package."""
        _cmd: t.List[str] = ["dpkg", "-i", str(path)]
        try:
            result = subprocess.check_output(_cmd, universal_newlines=True)
            logger.debug(result)
            logger.info("Install deb package %s from %s success", name, path)
        except subprocess.CalledProcessError as exc:
            raise apt.PackageError(f"Fail to install deb {name} from {path}") from exc


class StorCLIInstallStrategy(DebInstallStrategy):  # pylint: disable=R0903
    """Strategy to install storcli."""

    def install(self, name: str, path: Path) -> None:
        """Install storecli."""
        super().install(name, path)
        copy_to_snap_common_bin(
            filename="storcli",
            source=Path("/opt/MegaRAID/storcli/storcli64"),
        )


class VendorHelper:
    """Helper to install vendor's tools."""

    @property
    def strategies(self) -> t.Dict[str, InstallStrategyABC]:
        """Define strategies for every vendor's tools."""
        return {
            "storecli-deb": StorCLIInstallStrategy(),
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
                install_strategy = self.strategies.get(name)
                if install_strategy and path:
                    install_strategy.install(name, path)
                else:
                    logger.warning("Could not find install strategy for tool %s", name)
