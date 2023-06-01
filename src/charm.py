#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
import os
import typing as t

import ops
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, ModelError

from exporter import Exporter
from vendor import VendorHelper

logger = logging.getLogger(__name__)


class PrometheusHardwareExporterCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: t.Any) -> None:
        """Init."""
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install_or_upgrade)
        self.framework.observe(self.on.upgrade_charm, self._on_install_or_upgrade)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Initialise helpers, etc.
        self._snap_path: t.Optional[str] = None
        self._snap_path_set = False
        self.vendor_helper = VendorHelper()

        self.exporter = Exporter(self, "exporter")
        self._stored.set_default(installed=False, config={})

    def _on_install_or_upgrade(self, _: EventBase) -> None:
        """Install and upgrade."""
        self.vendor_helper.install(self.model.resources)

        self._stored.installed = True

        self.model.unit.status = ActiveStatus("Install complete")
        logger.info("Install complete")

    @property
    def snap_path(self) -> t.Optional[str]:
        """Get local path to exporter snap.

        Returns:
          snap_path: the path to the snap file
        """
        if not self._snap_path_set:
            try:
                self._snap_path = str(self.model.resources.fetch("exporter-snap").absolute())
                if not os.path.getsize(self._snap_path) > 0:
                    self._snap_path = None
            except ModelError:
                self._snap_path = None
            finally:
                self._snap_path_set = True
        return self._snap_path

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
        # Keep track of what model config options + some extra config related
        # information are changed. This can be helpful when we want to respond
        # to the change of a specific config option.
        change_set = set()
        model_config: t.Dict[str, t.Optional[str]] = dict(self.model.config.items())
        model_config.update({"exporter-snap": self.snap_path})
        for key, value in model_config.items():
            if key not in self._stored.config or self._stored.config[key] != value:  # type: ignore
                logger.info("Setting %s to: %s", key, value)
                self._stored.config[key] = value  # type: ignore
                change_set.add(key)

        self.exporter.on_config_changed(change_set)

        if not self._stored.installed:  # type: ignore
            logging.info(  # type: ignore
                "Config changed called before install complete, deferring event: %s",
                event.handle,
            )
            event.defer()
            return

        self.model.unit.status = ActiveStatus("Unit is ready")


if __name__ == "__main__":  # pragma: nocover
    ops.main(PrometheusHardwareExporterCharm)  # type: ignore
