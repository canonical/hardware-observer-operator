#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, Dict, Optional

import ops
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus

from service import Exporter
from vendor import VendorHelper

logger = logging.getLogger(__name__)


class PrometheusHardwareExporterCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: Any) -> None:
        """Init."""
        super().__init__(*args)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.install, self._on_install_or_upgrade)
        self.framework.observe(self.on.upgrade_charm, self._on_install_or_upgrade)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)

        self.vendor_helper = VendorHelper()

        self.exporter = Exporter(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": int(self.model.config["exporter-port"])}
            ],
        )
        self._stored.set_default(installed=False, config={})

    def _on_install_or_upgrade(self, _: EventBase) -> None:
        """Install and upgrade."""
        self.exporter.install()
        self.vendor_helper.install(self.model.resources)
        self._stored.installed = True
        self.model.unit.status = ActiveStatus("Install complete")
        logger.info("Install complete")

    def _on_remove(self, _: EventBase) -> None:
        """Uninstall event."""
        self.exporter.uninstall()
        logger.info("Remove complete")

    def _on_update_status(self, _: EventBase) -> None:
        if not self.exporter.check_relation():
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
            return
        if not self.exporter.check_health():
            self.model.unit.status = BlockedStatus("Exporter is unhealthy")
            return
        self.model.unit.status = ActiveStatus("Unit is ready")

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
        # Keep track of what model config options + some extra config related
        # information are changed. This can be helpful when we want to respond
        # to the change of a specific config option.
        change_set = set()
        model_config: Dict[str, Optional[str]] = dict(self.model.config.items())
        for key, value in model_config.items():
            if key not in self._stored.config or self._stored.config[key] != value:  # type: ignore
                logger.info("Setting %s to: %s", key, value)
                self._stored.config[key] = value  # type: ignore
                change_set.add(key)

        if not self._stored.installed:  # type: ignore
            logging.info(  # type: ignore
                "Config changed called before install complete, deferring event: %s",
                event.handle,
            )
            event.defer()
            return

        self.exporter.on_config_changed(change_set)
        self.model.unit.status = ActiveStatus("Unit is ready")

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.vendor_helper.remove(self.model.resources)


if __name__ == "__main__":  # pragma: nocover
    ops.main(PrometheusHardwareExporterCharm)  # type: ignore
