"""Exporter."""
import typing as t
from functools import wraps
from logging import getLogger

import ops
from charms.operator_libs_linux.v2 import snap
from ops.framework import Object

from config import EXPORTER_NAME

logger = getLogger(__name__)


def check_snap_installed(func: t.Callable) -> t.Callable:
    """Ensure snap is installed before running a snap operation."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):  # type: ignore
        """Wrap func."""
        try:
            self._exporter = (  # pylint: disable=W0212
                self._exporter or snap.SnapCache()[EXPORTER_NAME]  # pylint: disable=W0212
            )
            logger.info("%s exporter snap.", func.__name__.capitalize())
            if not (self._exporter and self._exporter.present):  # pylint: disable=W0212
                msg = f"Cannot {func.__name__} the exporter because it is not installed."
                raise snap.SnapNotFoundError(msg)
            func(self, *args, **kwargs)
            logger.info("%s exporter snap - Done", func.__name__.capitalize())
        except snap.SnapNotFoundError as err:
            logger.error(str(err))
            logger.error("%s exporter snap - Failed", func.__name__.capitalize())

    return wrapper


class Exporter(Object):
    """A class representing the exporter and the metric endpoints."""

    def __init__(self, charm: ops.CharmBase, key: str, *args: t.Any, **kwargs: t.Any) -> None:
        """Initialize the class."""
        super().__init__(charm, key, *args, **kwargs)
        self._exporter: t.Optional[snap.Snap] = None
        self._charm = charm
        self._stored = self._charm._stored  # type: ignore

    def install_or_refresh(self, channel: t.Optional[str] = None) -> None:
        """Install or refresh the exporter snap."""
        logger.info("Installing exporter snap.")
        channel = channel or self._stored.config["exporter-channel"]
        try:
            if self._stored.config["exporter-snap"]:
                snap.install_local(self._stored.config["exporter-snap"], dangerous=True)
            else:
                snap.add([EXPORTER_NAME], channel=channel)

            logger.info("Installed exportr snap.")
        except snap.SnapError as err:
            logger.error(str(err))
        else:
            logger.info("Exporter snap installed.")

    def on_config_changed(self, change_set: t.Set) -> None:
        """Trigger on hook config_changed."""
        observe = set(["exporter-snap", "exporter-channel"])
        if len(observe.intersection(change_set)) > 0:
            logger.info("Exported config changed")
        if "exporter-snap" in change_set or "exporter-channel" in change_set:
            self.install_or_refresh()

        # Below lines should be remove after.
        # It's only for testing before we make sure the scope of relation.
        self.install_or_refresh()

    @check_snap_installed
    def start(self) -> None:
        """Start the exporter daemon."""
        if isinstance(self._exporter, snap.Snap):
            self._exporter.start()
