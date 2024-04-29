#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from time import sleep
from typing import Any, Dict, List, Optional, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from redfish import redfish_client
from redfish.rest.v1 import InvalidCredentialsError

from config import (
    EXPORTER_CRASH_MSG,
    EXPORTER_HEALTH_RETRY_COUNT,
    EXPORTER_HEALTH_RETRY_TIMEOUT,
    REDFISH_MAX_RETRY,
    REDFISH_TIMEOUT,
    HWTool,
)
from hardware import get_bmc_address
from hw_tools import HWToolHelper, get_hw_tool_enable_list
from service import Exporter, ExporterError

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
            # Setting scrape_timeout as collect_timeout in the `duration` format specified in
            # https://prometheus.io/docs/prometheus/latest/configuration/configuration/#duration
            scrape_configs=[{"scrape_timeout": f"{int(self.model.config['collect-timeout'])}s"}],
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
        self.framework.observe(self.on.redetect_hardware_action, self._on_redetect_hardware)

        self._stored.set_default(
            exporter_installed=False,
            resource_installed=False,
            # Storing only the values from `HWTool` because entire HWTool
            # cannot be stored in _stored. Only simple types can be stored.
            enabled_hw_tool_list_values=[],
        )
        self.num_cos_agent_relations = self.get_num_cos_agent_relations("cos-agent")

    def get_enabled_hw_tool_list_values(self) -> List[str]:
        """Get hw tool list from stored or from machine if not in stored."""
        if not self._stored.enabled_hw_tool_list_values:  # type: ignore[truthy-function]
            self._stored.enabled_hw_tool_list_values = [  # type: ignore[unreachable]
                tool.value for tool in get_hw_tool_enable_list()
            ]
        return self._stored.enabled_hw_tool_list_values  # type: ignore[return-value]

    def get_hw_tools_from_values(self, hw_tool_values: List[str]) -> List[HWTool]:
        """Get HWTool objects from hw tool values."""
        return [HWTool(value) for value in hw_tool_values]

    def _on_redetect_hardware(self, event: ops.ActionEvent) -> None:
        """Detect hardware tool list and option to rerun the install hook."""
        current_hw_tools_value_list = self.get_enabled_hw_tool_list_values()
        current_hw_tools_str_list = [str(tool) for tool in current_hw_tools_value_list]
        current_hw_tools_str_list.sort()

        detected_hw_tool_list = get_hw_tool_enable_list()
        detected_hw_tool_str_list = [tool.value for tool in detected_hw_tool_list]
        detected_hw_tool_str_list.sort()

        hw_change_detected = False
        if current_hw_tools_str_list != detected_hw_tool_str_list:
            hw_change_detected = True

        result = {
            "hardware-change-detected": hw_change_detected,
            "current-hardware-tools": ",".join(current_hw_tools_str_list),
            "update-hardware-tools": False,
        }
        # Show compare lists if hw_change_detected
        if hw_change_detected:
            result["detected-hardware-tools"] = ",".join(detected_hw_tool_str_list)

        if event.params["apply"] and hw_change_detected:
            # Reset the value in local Store
            self._stored.enabled_hw_tool_list_values = detected_hw_tool_str_list
            event.log(f"Run install hook with enable tools: {','.join(detected_hw_tool_str_list)}")
            self._on_install_or_upgrade(event=event)
            result["update-hardware-tools"] = True
        event.set_results(result)

    def _on_install_or_upgrade(self, event: EventBase) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")

        enabled_hw_tool_list_values = self.get_enabled_hw_tool_list_values()
        enabled_hw_tool_list = self.get_hw_tools_from_values(enabled_hw_tool_list_values)

        resource_installed, msg = self.hw_tool_helper.install(
            self.model.resources, enabled_hw_tool_list
        )
        self._stored.resource_installed = resource_installed

        if not resource_installed:
            logger.warning(msg)
            self.model.unit.status = BlockedStatus(msg)
            return

        # Install exporter
        self.model.unit.status = MaintenanceStatus("Installing exporter...")
        success = self.exporter.install(
            int(self.model.config["exporter-port"]),
            self.model.config["exporter-log-level"],
            self.get_redfish_conn_params(enabled_hw_tool_list),
            int(self.model.config["collect-timeout"]),
            enabled_hw_tool_list,
        )
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
        self.hw_tool_helper.remove(
            self.model.resources,
            self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values()),
        )
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

        config_valid, config_valid_message = self.validate_exporter_configs()
        if not config_valid:
            self.model.unit.status = BlockedStatus(config_valid_message)
            return

        hw_tool_ok, error_msg = self.hw_tool_helper.check_installed(
            self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values())
        )
        if not hw_tool_ok:
            self.model.unit.status = BlockedStatus(error_msg)
            return

        if not self.exporter.check_health():
            logger.warning("Exporter health check - failed.")
            # if restart isn't successful, an ExporterError exception will be raised here
            self.restart_exporter()

        self.model.unit.status = ActiveStatus("Unit is ready")

    def restart_exporter(self) -> None:
        """Restart exporter service with retry."""
        try:
            for i in range(1, EXPORTER_HEALTH_RETRY_COUNT + 1):
                logger.warning("Restarting exporter - %d retry", i)
                self.exporter.restart()
                sleep(EXPORTER_HEALTH_RETRY_TIMEOUT)
                if self.exporter.check_active():
                    logger.info("Exporter active after restart.")
                    break
            if not self.exporter.check_active():
                logger.error("Failed to restart the exporter.")
                raise ExporterError(EXPORTER_CRASH_MSG)
        except Exception as err:  # pylint: disable=W0718
            logger.error("Exporter crashed unexpectedly: %s", err)
            raise ExporterError(EXPORTER_CRASH_MSG) from err

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
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

            success = self.exporter.template.render_config(
                port=int(self.model.config["exporter-port"]),
                level=self.model.config["exporter-log-level"],
                redfish_conn_params=self.get_redfish_conn_params(
                    self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values())
                ),
                collect_timeout=int(self.model.config["collect-timeout"]),
                hw_tools=self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values()),
            )
            if not success:
                message = "Failed to configure exporter, please check if the server is healthy."
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
        self.exporter.enable()
        self.exporter.start()
        logger.info("Start and enable exporter service")
        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporter when relation departed."""
        if self._stored.exporter_installed:  # type: ignore[truthy-function]
            self.exporter.stop()
            self.exporter.disable()
            logger.info("Stop and disable exporter service")
        self._on_update_status(event)

    def get_redfish_conn_params(self, enabled_hw_tool_list: List[HWTool]) -> Dict[str, Any]:
        """Get redfish connection parameters if redfish is available."""
        if HWTool.REDFISH not in enabled_hw_tool_list:
            logger.warning("Redfish unavailable, disregarding redfish config options...")
            return {}
        return {
            "host": f"https://{get_bmc_address()}",
            "username": self.model.config.get("redfish-username", ""),
            "password": self.model.config.get("redfish-password", ""),
        }

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        port = int(self.model.config["exporter-port"])
        if not 1 <= port <= 65535:
            logger.error("Invalid exporter-port: port must be in [1, 65535].")
            return False, "Invalid config: 'exporter-port'"

        level = self.model.config["exporter-log-level"]
        allowed_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level.upper() not in allowed_choices:
            logger.error(
                "Invalid exporter-log-level: level must be in %s (case-insensitive).",
                allowed_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"

        # Note we need to use `is False` because `None` means redfish is not
        # available.
        if self.redfish_conn_params_valid is False:
            logger.error("Invalid redfish credentials.")
            return False, "Invalid config: 'redfish-username' or 'redfish-password'"

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

    @property
    def redfish_conn_params_valid(self) -> Optional[bool]:
        """Check if redfish connections parameters is valid or not.

        If the redfish connection params is not available this property returns
        None. Otherwise, it verifies the connection parameters. If the redfish
        connection parameters are valid, it returns True; if not valid, it
        returns False.
        """
        redfish_conn_params = self.get_redfish_conn_params(
            self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values())
        )
        if not redfish_conn_params:
            return None

        redfish_obj = None
        try:
            redfish_obj = redfish_client(
                base_url=redfish_conn_params.get("host", ""),
                username=redfish_conn_params.get("username", ""),
                password=redfish_conn_params.get("password", ""),
                timeout=REDFISH_TIMEOUT,
                max_retry=REDFISH_MAX_RETRY,
            )
            redfish_obj.login(auth="session")
        except InvalidCredentialsError as e:
            result = False
            logger.error("invalid redfish credential: %s", str(e))
        except Exception as e:  # pylint: disable=W0718
            result = False
            logger.error("cannot connect to redfish: %s", str(e))
        else:
            result = True
        finally:
            # Make sure to close connection at the end
            if redfish_obj:
                redfish_obj.logout()

        return result


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
