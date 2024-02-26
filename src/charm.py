#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from time import sleep
from typing import Any, Dict, Optional, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, ErrorStatus, MaintenanceStatus, StatusBase

from config import (
    EXPORTER_DEFAULT_PORT,
    EXPORTER_HEALTH_RETRY_COUNT,
    EXPORTER_HEALTH_RETRY_TIMEOUT,
    HWTool,
)
from hardware import get_bmc_address
from hw_tools import HWToolHelper, bmc_hw_verifier
from service import Exporter

logger = logging.getLogger(__name__)


class HardwareObserverCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: Any) -> None:
        """Init."""
        super().__init__(*args)
        self.hw_tool_helper = HWToolHelper()

        # Add refresh_events to COSAgentProvider to update relation data when
        # config changed (default behavior) and upgrade charm. This is useful
        # for updating alert rules.
        self.cos_agent_provider = COSAgentProvider(
            self,
            refresh_events=[self.on.config_changed, self.on.upgrade_charm],
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

        self._stored.set_default(
            config={},
            exporter_installed=False,
            resource_installed=False,
        )
        self.num_cos_agent_relations = self.get_num_cos_agent_relations("cos-agent")

    def _on_install_or_upgrade(self, event: ops.InstallEvent) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")

        resource_installed, msg = self.hw_tool_helper.install(self.model.resources)
        self._stored.resource_installed = resource_installed

        if not resource_installed:
            logger.warning(msg)
            self.model.unit.status = BlockedStatus(msg)
            return

        # Install exporter
        self.model.unit.status = MaintenanceStatus("Installing exporter...")
        success, err_msg = self.validate_exporter_configs()
        if not success:
            self.model.unit.status = BlockedStatus(err_msg)
            return

        port = self.model.config.get("exporter-port", EXPORTER_DEFAULT_PORT)
        level = self.model.config.get("exporter-log-level", "INFO")
        redfish_creds = self._get_redfish_creds()
        success = self.exporter.install(port, level, redfish_creds)
        self._stored.exporter_installed = success
        if not success:
            msg = "Failed to install exporter, please refer to `juju debug-log`"
            logger.error(msg)
            self.model.unit.status = BlockedStatus(msg)
            return
        self._on_update_status(event)

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.hw_tool_helper.remove(self.model.resources)
        self._stored.resource_installed = False
        success = self.exporter.uninstall()
        if not success:
            msg = "Failed to uninstall exporter, please refer to `juju debug-log`"
            # we probably don't need to set any status here because the charm
            # will go away soon, so only logging is enough
            logger.warning(msg)
        self._stored.exporter_installed = not success
        logger.info("Remove complete")

    def _on_update_status(self, _: EventBase) -> None:  # noqa: C901
        """Update the charm's status."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            # The charm should be in BlockedStatus with install failed msg
            return  # type: ignore[unreachable]

        if not self.exporter_enabled:
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
            return

        if self.too_many_cos_agent_relations:
            self.model.unit.status = BlockedStatus("Cannot relate to more than one grafana-agent")
            return

        config_valied, confg_valid_message = self.validate_exporter_configs()
        if not config_valied:
            self.model.unit.status = BlockedStatus(confg_valid_message)
            return

        hw_tool_ok, error_msg = self.hw_tool_helper.check_installed()
        if not hw_tool_ok:
            self.model.unit.status = BlockedStatus(error_msg)
            return

        if not self.exporter.check_health():
            logger.warning("Exporter health check - failed.")
            restart_ok, restart_status = self.restart_exporter()
            if not restart_ok and restart_status is not None:
                self.model.unit.status = restart_status
                return

        self.model.unit.status = ActiveStatus("Unit is ready")

    def restart_exporter(self) -> Tuple[bool, Optional[StatusBase]]:
        """Restart exporter service with retry."""
        try:
            for i in range(1, EXPORTER_HEALTH_RETRY_COUNT + 1):
                logger.warning("Restarting exporter - %d retry", i)
                self.exporter.restart()
                sleep(EXPORTER_HEALTH_RETRY_TIMEOUT)
                if self.exporter.check_active():
                    logger.info("Exporter restarted.")
                    break
            if not self.exporter.check_active():
                logger.error("Failed to restart the exporter.")
                return False, ErrorStatus(
                    "Exporter crashed unexpectedly, please refer to systemd logs..."
                )
        except Exception as err:  # pylint: disable=W0718
            logger.error("Exporter crashed unexpectedly: %s", err)
            return False, ErrorStatus(
                "Exporter crashed unexpectedly, please refer to systemd logs..."
            )
        return True, None

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
        # Keep track of what model config options + some extra config related
        # information are changed. This can be helpful when we want to respond
        # to the change of a specific config option.
        change_set = set()
        model_config: Dict[str, Optional[str]] = dict(self.model.config.items())
        for key, value in model_config.items():
            if (
                key not in self._stored.config  # type: ignore[operator]
                or self._stored.config[key] != value  # type: ignore[index]
            ):
                logger.info("Setting %s to: %s", key, value)
                self._stored.config[key] = value  # type: ignore
                change_set.add(key)

        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            logging.info(  # type: ignore[unreachable]
                "Config changed called before install complete, deferring event: %s",
                event.handle,
            )
            event.defer()

        if self.exporter_enabled:
            success, message = self.validate_exporter_configs()
            if not success:
                self.model.unit.status = BlockedStatus(message)
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
                port = self.model.config.get("exporter-port", EXPORTER_DEFAULT_PORT)
                level = self.model.config.get("exporter-log-level", "INFO")

                redfish_creds = self._get_redfish_creds()
                success = self.exporter.template.render_config(
                    port=port, level=level, redfish_creds=redfish_creds
                )
                if not success:
                    message = (
                        "Failed to configure exporter, please check if the server is healthy."
                    )
                    self.model.unit.status = BlockedStatus(message)
                    return
                self.exporter.restart()

        self._on_update_status(event)

    def _on_cos_agent_relation_joined(self, event: EventBase) -> None:
        """Start the exporter when relation joined."""
        if (
            not self._stored.resource_installed  # type: ignore[truthy-function]
            or not self._stored.exporter_installed  # type: ignore[truthy-function]
        ):
            logger.info(  # type: ignore[unreachable]
                "Defer cos-agent relation join because exporter or resources is not ready yet."
            )
            event.defer()
            return
        self.exporter.start()
        logger.info("Start exporter service")
        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporter when relation departed."""
        if self._stored.exporter_installed:  # type: ignore[truthy-function]
            self.exporter.stop()
            logger.info("Stop exporter service")
        self._on_update_status(event)

    def _get_redfish_creds(self) -> Dict[str, str]:
        """Provide redfish config if redfish is available, else empty dict."""
        bmc_tools = bmc_hw_verifier()
        if HWTool.REDFISH in bmc_tools:
            bmc_address = get_bmc_address()
            redfish_creds = {
                # Force to use https as default protocol
                "host": f"https://{bmc_address}",
                "username": self.model.config.get("redfish-username", ""),
                "password": self.model.config.get("redfish-password", ""),
            }
        else:
            redfish_creds = {}
        return redfish_creds

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        port = int(self.model.config.get("exporter-port", EXPORTER_DEFAULT_PORT))
        if not 1 <= port <= 65535:
            logger.error("Invalid exporter-port: port must be in [1, 65535].")
            return False, "Invalid config: 'exporter-port'"

        level = self.model.config.get("exporter-log-level", "")
        allowed_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level.upper() not in allowed_choices:
            logger.error(
                "Invalid exporter-log-level: level must be in %s (case-insensitive).",
                allowed_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"

        return True, "Exporter config is valid."

    def get_num_cos_agent_relations(self, relation_name: str) -> int:
        """Get the number of relation given a relation_name."""
        relations = self.model.relations.get(relation_name, [])
        return len(relations)

    @property
    def exporter_enabled(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_cos_agent_relations != 0

    @property
    def too_many_cos_agent_relations(self) -> bool:
        """Return True if there're more than one cos-agent relation."""
        return self.num_cos_agent_relations > 1


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
