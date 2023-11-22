#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, Dict, List, Optional

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus

from config import EXPORTER_COLLECTOR_MAPPING
from hardware import get_bmc_address
from hw_tools import HWToolHelper, get_hw_tool_white_list, redfish_available
from service import Exporter

logger = logging.getLogger(__name__)


class HardwareObserverCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: Any) -> None:
        """Init."""
        super().__init__(*args)
        self.hw_tool_helper = HWToolHelper()

        self.cos_agent_provider = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": int(self.model.config["exporter-port"])}
            ],
        )
        self.exporter = Exporter(self.charm_dir)

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install_or_upgrade)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_install_or_upgrade)
        self.framework.observe(
            self.on.cos_agent_relation_joined, self._on_cos_agent_relation_joined
        )
        self.framework.observe(
            self.on.cos_agent_relation_departed, self._on_cos_agent_relation_departed
        )

        self._stored.set_default(installed=False, config={}, blocked_msg="")

    def _on_install_or_upgrade(self, event: ops.InstallEvent) -> None:
        """Install and upgrade."""
        port = self.model.config.get("exporter-port", "10000")
        level = self.model.config.get("exporter-log-level", "INFO")
        collectors = self._discover_collectors()
        redfish_options = self._get_redfish_options()
        self.exporter.install(
            port=port,
            level=level,
            collectors=collectors,
            redfish_options=redfish_options,
        )

        installed, msg = self.hw_tool_helper.install(self.model.resources)
        self._stored.installed = installed

        if not installed:
            logger.info(msg)
            self._stored.blocked_msg = msg
            self._on_update_status(event)
            return

        self._stored.installed = True
        self._stored.blocked_msg = ""
        self.model.unit.status = ActiveStatus("Install complete")
        logger.info("Install complete")

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.hw_tool_helper.remove(self.model.resources)
        self.exporter.uninstall()
        logger.info("Remove complete")

    def _on_update_status(self, _: EventBase) -> None:
        """Update the charm's status."""
        if self._stored.installed is not True and self._stored.blocked_msg != "":
            self.model.unit.status = BlockedStatus(self._stored.blocked_msg)  # type: ignore
            return
        if not self.model.get_relation("cos-agent"):
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
            return
        if not self.exporter.check_health():
            self.model.unit.status = BlockedStatus("Exporter is unhealthy")
            return
        if not self.exporter.check_active():
            self.model.unit.status = BlockedStatus("Exporter is not running")
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

        exporter_configs = {
            "exporter-port",
            "exporter-log-level",
            "redfish-host",
            "redfish-username",
            "redfish-password",
        }
        if exporter_configs.intersection(change_set):
            logger.info("Detected changes in exporter config.")

            port = self.model.config.get("exporter-port", "10000")
            level = self.model.config.get("exporter-log-level", "INFO")
            collectors = self._discover_collectors()
            redfish_options = self._get_redfish_options()
            success = self.exporter.template.render_config(
                port=port,
                level=level,
                collectors=collectors,
                redfish_options=redfish_options,
            )

            # First condition prevent the exporter from starting at when the
            # charm just installed; the second condition tries to recover the
            # exporter from failed status.
            if success and self.exporter.check_active() or not self.exporter.check_health():
                self.exporter.restart()

        self._on_update_status(event)

    def _on_cos_agent_relation_joined(self, event: EventBase) -> None:
        """Start the exporter when relation joined."""
        self.exporter.start()
        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporter when relation departed."""
        self.exporter.stop()
        self._on_update_status(event)

    def _discover_collectors(self) -> List[str]:
        hw_tools = get_hw_tool_white_list()
        collectors = []
        for tool in hw_tools:
            collector = EXPORTER_COLLECTOR_MAPPING.get(tool)
            if collector is not None:
                collectors += collector
        return collectors

    def _get_redfish_options(self) -> Dict[str, Any]:
        """Get redfish config options."""
        bmc_address = get_bmc_address()
        redfish_options = {
            "enable": redfish_available(),
            # Force to use https as default protocol
            "host": f"https://{bmc_address}",
            "username": self.model.config.get("redfish-username", ""),
            "password": self.model.config.get("redfish-password", ""),
        }
        return redfish_options


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
