#!/usr/bin/env python3
# Copyright 2023 jneo8
# See LICENSE file for licensing details.
"""Charm the application."""
import logging
from time import sleep
from typing import Any, Dict, List, Optional, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, ErrorStatus, MaintenanceStatus, StatusBase

from config import EXPORTER_HEALTH_RETRY_COUNT, EXPORTER_HEALTH_RETRY_TIMEOUT, HWTool
from hardware import get_bmc_address
from hw_tools import HWToolHelper
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

        self._stored.set_default(
            config={},
            exporter_installed=False,
            installed=False,
            hw_white_list=[],
            missing_resources=[],
            failed_strategies=[],
            installed_strategies=[],
        )
        self.num_cos_agent_relations = self.get_num_cos_agent_relations("cos-agent")

    def _log_stored(self) -> None:
        """Logger print _stored information."""
        msg = (
            "Hw tool state: "  # type: ignore
            f"hw_white_list: {list(self._stored.hw_white_list)}"
            f" missing_resources: {list(self._stored.missing_resources)}"
            f" installed_strategies: {list(self._stored.installed_strategies)}"
            f" failed_strategies: {list(self._stored.failed_strategies)}"
        )
        logger.info(msg)

    def str_list_to_hwtool_list(self, values: List[str]) -> List[HWTool]:
        """Convent list of enum's value to enum."""
        return [HWTool(value) for value in values]

    @property
    def state_resource_installed(self) -> bool:
        """Return True if resources installed completely."""
        if (
            len(self._stored.missing_resources) > 0  # type: ignore
            or len(self._stored.failed_strategies) > 0  # type: ignore
        ):
            return False
        return True

    @property
    def state_missing_resource(self) -> bool:
        """Return True if charm is missing resources."""
        if len(self._stored.missing_resources) == 0:  # type: ignore
            return False
        return True

    @property
    def state_failed_install_strategies(self) -> bool:
        """Return True if there are any strategy install failed."""
        if len(self._stored.failed_strategies) == 0:  # type: ignore
            return False
        return True

    @property
    def state_exporter_installed(self) -> bool:
        """Return True if charm install exporter succeeded."""
        return self._stored.exporter_installed  # type: ignore

    @property
    def state_exporter_health(self) -> bool:
        """Return True if exporter is health."""
        health = self.exporter.check_health()
        if not health:
            logger.warning("Exporter health check - failed.")
        return health

    @property
    def state_exporter_enabled(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_cos_agent_relations != 0

    @property
    def state_too_many_cos_agent_relation(self) -> bool:
        """Return True if there're more than one cos-agent relation."""
        return self.num_cos_agent_relations > 1

    @property
    def state_msg_missing_resources(self) -> str:
        """Message for missing resources."""
        return f"Missing resources: {list(self._stored.missing_resources)}"  # type: ignore

    @property
    def state_msg_failed_install_strategies(self) -> str:
        """Message for failed install strategies."""
        return (
            "Fail install strategies:"
            f" {list(self._stored.installed_strategies)}"  # type: ignore
        )

    @property
    def state_msg_resource_installed(self) -> str:
        """Return either message for missing resources or failed_install_strategies."""
        if self.state_missing_resource:
            return self.state_msg_missing_resources
        return self.state_msg_failed_install_strategies

    def _on_install_or_upgrade(self, event: ops.InstallEvent) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")
        (
            hw_white_list,
            missing_resources,
            installed_strategies,
            failed_strategies,
        ) = self.hw_tool_helper.install(self.model.resources)

        self._stored.hw_white_list = [tool.value for tool in hw_white_list]
        self._stored.missing_resources = missing_resources

        self._log_stored()

        # Missing resources, need user manually upload the resources.
        if self.state_missing_resource:
            msg = self.state_msg_missing_resources
            logger.warning(msg)
            self.model.unit.status = BlockedStatus(msg)
            return

        # Only update if not missing resources, otherwise they will be overwrite
        # to empty.
        self._stored.failed_strategies = [tool.value for tool in failed_strategies]
        self._stored.installed_strategies = [tool.value for tool in installed_strategies]

        # The strategies fail for unexpected error, get into error status
        # and wait for manually fix.
        if self.state_failed_install_strategies:
            msg = self.state_msg_failed_install_strategies
            logger.error(msg)
            self.model.unit.status = ErrorStatus(msg)

        # Install exporter
        if not self.state_exporter_installed:
            self.model.unit.status = MaintenanceStatus("Installing exporter...")
            # Set to blocked status if config is not valid.
            success, err_msg = self.validate_exporter_configs()
            if not success:
                self.model.unit.status = BlockedStatus(err_msg)
                return

            port = self.model.config.get("exporter-port", "10000")
            level = self.model.config.get("exporter-log-level", "INFO")
            logger.info("Get redfish creds." "")
            redfish_creds = self._get_redfish_creds()

            # Set to ErrorStatus if exporter fail to start
            exporter_install_success = self.exporter.install(
                port,
                level,
                redfish_creds,
                self.str_list_to_hwtool_list(self._stored.hw_white_list),
            )
            self._stored.exporter_installed = exporter_install_success
            if not exporter_install_success:
                msg = "Failed to install exporter, please refer to `juju debug-log`"
                logger.error(msg)
                self.model.unit.status = ErrorStatus(msg)
                return

        self._on_update_status(event)

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.hw_tool_helper.remove(self.model.resources)
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
        self._log_stored()
        if not self.state_resource_installed:
            msg = self.state_msg_resource_installed
            self.model.unit.status = BlockedStatus(msg)
            return

        if not self.state_exporter_enabled:
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
            return

        if self.state_too_many_cos_agent_relation:
            self.model.unit.status = BlockedStatus("Cannot relate to more than one grafana-agent")
            return

        installed_strategies, failed_strategies = self.hw_tool_helper.check_installed()
        self._stored.failed_strategies = [tool.value for tool in failed_strategies]
        self._stored.installed_strategies = [tool.value for tool in installed_strategies]

        # The strategies fail for unexpected error, get into error status
        # and wait for manually fix.
        if self.state_failed_install_strategies:
            msg = self.state_msg_failed_install_strategies
            logger.error(msg)
            self.model.unit.status = ErrorStatus(msg)
            return

        # Check exporter health and try to restart exporter service
        if not self.state_exporter_health:
            restart_ok, restart_status = self.restart_exporter()
            if not restart_ok and restart_status is not None:
                self.model.unit.status = restart_status
                return

        self.model.unit.status = ActiveStatus("Unit is ready")

    def restart_exporter(self) -> Tuple[bool, Optional[StatusBase]]:
        """Restart exporter with retry."""
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
            if key not in self._stored.config or self._stored.config[key] != value:  # type: ignore
                logger.info("Setting %s to: %s", key, value)
                self._stored.config[key] = value  # type: ignore
                change_set.add(key)

        if not self.state_resource_installed:
            logging.info(
                "Config changed called before resource install complete, deferring event: %s",
                event.handle,
            )
            event.defer()

        if self.state_exporter_enabled:
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
                port = self.model.config.get("exporter-port", "10000")
                level = self.model.config.get("exporter-log-level", "INFO")

                redfish_creds = self._get_redfish_creds()
                success = self.exporter.template.render_config(
                    port=port,
                    level=level,
                    redfish_creds=redfish_creds,
                    hw_white_list=self.str_list_to_hwtool_list(
                        self._stored.hw_white_list  # type: ignore
                    ),
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
        self.exporter.start()
        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporter when relation departed."""
        self.exporter.stop()
        self._on_update_status(event)

    def _get_redfish_creds(self) -> Dict[str, str]:
        """Provide redfish config if redfish is available, else empty dict."""
        if HWTool.REDFISH in self.str_list_to_hwtool_list(
            self._stored.hw_white_list  # type: ignore
        ):
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
        port = int(self.model.config.get("exporter-port", "10000"))
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


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
