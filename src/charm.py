#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, Dict, Optional

import ops
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, ErrorStatus, MaintenanceStatus

import cos_agent
import service
from config import EXPORTER_RELATION_NAME, HWTool
from hardware import get_bmc_address
from hw_tools import HWToolHelper

logger = logging.getLogger(__name__)


class HardwareObserverCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: Any) -> None:
        """Init."""
        super().__init__(*args)
        self.hw_tool_helper = HWToolHelper()
        self.exporter = service.Exporter(self.charm_dir)
        self.cos_agent_relation_handler = cos_agent.Handler(
            self,
            exporter=self.exporter,
            relation_name=EXPORTER_RELATION_NAME,
            metrics_endpoints=[
                {
                    "path": "/metrics",
                    "port": int(
                        self.model.config["exporter-port"],
                    ),
                }
            ],
        )

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install_or_upgrade)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_install_or_upgrade)

        self._stored.set_default(
            config={},
            exporter_installed=False,
            resource_install_result={},
        )

    def _on_install_or_upgrade(self, _: ops.InstallEvent) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")
        resource_white_list = self.hw_tool_helper.get_resource_white_list(self.model.resources)
        resource_install_result = self.hw_tool_helper.install(
            resource_white_list,
            resource_black_list=self._stored.resource_install_result,  # type: ignore[arg-type]
        )
        self._stored.resource_install_result = resource_install_result
        if not all(resource_install_result.values()):
            failed_resources = [r for r, s in resource_install_result.items() if not s]
            msg = f"Failed to install resources: {', '.join(failed_resources)}"
            logger.error(msg)
            self.model.unit.status = ErrorStatus(msg)
            return

        if self._stored.exporter_installed is not True:
            self.model.unit.status = MaintenanceStatus("Installing exporter...")
            success = self.cos_agent_relation_handler.install_exporter()
            self._stored.exporter_installed = success
            if not success:
                msg = "Failed to install exporter, please refer to `juju debug-log`"
                logger.error(msg)
                self.model.unit.status = ErrorStatus(msg)
                return

        self.update_status()

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        self.hw_tool_helper.remove(self.model.resources)
        self._stored.resource_install_result = {}
        success = self.cos_agent_relation_handler.uninstall_exporter()
        if not success:
            msg = "Failed to uninstall exporter, please refer to `juju debug-log`"
            logger.warning(msg)
        self._stored.exporter_installed = not success
        logger.info("Remove complete")

    def _on_update_status(self, _: EventBase) -> None:
        """Update the charm's status."""
        self.update_status()

    def _on_config_changed(self, _: EventBase) -> None:
        """Reconfigure charm."""
        change_set = self.update_config_store()

        if self.cos_agent_relation_handler.exporter_enabled:
            options = self.get_exporter_configs()
            success, message = self.cos_agent_relation_handler.validate_exporter_configs(options)
            if not success:
                self.model.unit.status = BlockedStatus(message)
                return

            success = self.cos_agent_relation_handler.configure_exporter(options, change_set)
            if not success:
                message = "Failed to configure exporter, please check if the server is healthy."
                self.model.unit.status = BlockedStatus(message)
                return

        self.update_status()

    def update_status(self) -> None:
        """Update the charm's status."""
        if not self.cos_agent_relation_handler.exporter_enabled:
            self.model.unit.status = BlockedStatus(f"Missing relation: [{EXPORTER_RELATION_NAME}]")
            return

        if self.cos_agent_relation_handler.too_many_relations:
            self.model.unit.status = BlockedStatus("Cannot relate to more than one grafana-agent")
            return

        if (
            self.cos_agent_relation_handler.exporter_enabled
            and not self.cos_agent_relation_handler.exporter_online
        ):
            error_msg = "Exporter crashed unexpectedly, please refer to systemd logs..."
            self.model.unit.status = ErrorStatus(error_msg)
            return

        hw_tool_ok, error_msg = self.hw_tool_helper.check_status()
        if not hw_tool_ok:
            self.model.unit.status = ErrorStatus(error_msg)
            return

        self.model.unit.status = ActiveStatus("Unit is ready")

    def update_config_store(self) -> set:
        """Update the config store, and return a set of config options that are changed."""
        change_set = set()
        model_config: Dict[str, Optional[str]] = dict(self.model.config.items())
        for key, value in model_config.items():
            if key not in self._stored.config or self._stored.config[key] != value:  # type: ignore
                logger.info("Setting %s to: %s", key, value)
                self._stored.config[key] = value  # type: ignore
                change_set.add(key)
        return change_set

    def get_redfish_options(self) -> Dict[str, Any]:
        """Get redfish config options."""
        redfish_options = {
            "enable": False,
            "host": "",
            "username": self.model.config.get("redfish-username", ""),
            "password": self.model.config.get("redfish-password", ""),
        }

        bmc_address = get_bmc_address()
        if bmc_address:
            redfish_options["enable"] = True
            redfish_options["host"] = f"https://{bmc_address}"

        return redfish_options

    def get_exporter_configs(self) -> Dict[str, Any]:
        """Get the exporter related config options."""
        port = self.model.config.get("exporter-port", "10000")
        level = self.model.config.get("exporter-log-level", "INFO")
        collectors = self.hw_tool_helper.hw_collector_white_list
        redfish_options = {"enable": False}
        if HWTool.REDFISH in collectors:
            redfish_options = self.get_redfish_options()
        return {
            "port": port,
            "level": level,
            "collectors": collectors,
            "redfish_options": redfish_options,
        }


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
