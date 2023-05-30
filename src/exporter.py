"""Exporter."""
from functools import wraps
from logging import getLogger

from ops.framework import Object
from charms.operator_libs_linux.v2 import snap

from config import EXPORTER_NAME

logger = getLogger(__name__)


def check_snap_installed(func):
    """Ensure snap is installed before running a snap operation."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            fn = func.__name__
            self._exporter = self._exporter or snap.SnapCache()[EXPORTER_NAME]
            logger.info("%s exporter snap.", fn.capitalize())
            if not (self._exporter and self._exporter.present):
                msg = f"Cannot {fn} the exporter because it is not installed."
                raise snap.SnapNotFoundError(msg)
            func(self, *args, **kwargs)
            logger.info("%s exporter snap - Done", fn.capitalize())
        except snap.SnapNotFoundError as e:
            logger.error(str(e))
            logger.error("%s exporter snap - Failed", fn.capitalize())

    return wrapper


class Exporter(Object):

    def __init__(self, charm, key, *args, **kwargs):
        """Initialize the class."""
        super().__init__(charm, key, *args, **kwargs)
        self._exporter = None
        self._charm = charm
        self._stored = self._charm._stored

    def install_or_refresh(self, channel=None):
        """Install or refresh the exporter snap."""
        logger.info("Installing exporter snap.")
        channel = channel or self._stored.config["exporter-channel"]
        try:
            if self._stored.config["exporter-snap"]:
                snap.install_local(self._stored.config["exporter-snap"], dangerous=True)
            else:
                snap.add([EXPORTER_NAME], channel=channel)

            logger.info("Installed exportr snap.")
        except snap.SnapError as e:
            logger.error(str(e))
        else:
            logger.info("Exporter snap installed.")

    def on_config_changed(self, change_set):
        observe = set(["exporter-snap", "exporter-channel"])
        if len(observe.intersection(change_set)) > 0:
            logger.info("Exported config changed")
        if "exporter-snap" in change_set or "exporter-channel" in change_set:
            self.install_or_refresh()

        # This line should be remove after.
        # It's only for testing before we make sure the scope of relation.
        self.install_or_refresh()
