#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, List, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

import exporter_helpers
from hw_tools import get_hw_tool_enable_list, HWTool, HWToolHelper
from service import HardwareExporter

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
                {"path": "/metrics", "port": int(self.model.config["hardware-exporter-port"])}
            ],
            # Setting scrape_timeout as collect_timeout in the `duration` format specified in
            # https://prometheus.io/docs/prometheus/latest/configuration/configuration/#duration
            scrape_configs=[{"scrape_timeout": f"{int(self.model.config['collect-timeout'])}s"}],
        )

        self._stored.set_default(
            resource_installed=False,
            # Storing only the values from `HWTool` because entire HWTool
            # cannot be stored in _stored. Only simple types can be stored.
            enabled_hw_tool_list_values=[],
        )

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

        self.num_cos_agent_relations = self.get_num_cos_agent_relations("cos-agent")

    @property
    def exporters(self):
        exporters = []
        enable_hw_tool_list = self.get_hw_tools_from_values(self.get_enabled_hw_tool_list_values())
        for hw_tool in enable_hw_tool_list:

            if hw_tool in HardwareExporter.hw_tools():
                exporters.append(HardwareExporter(self.charm_dir, self.model.config, list(self._stored.enabled_hw_tool_list_values)))
                break

            # check and append other exporters here

        return exporters

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

        # Install exporters
        for exporter in self.exporters:
            exporter.install()

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

        # Remove exporters
        for exporter in self.exporters:
            exporter_helpers.remove_exporter(exporter, self.model)

    def _on_update_status(self, _: EventBase) -> None:  # noqa: C901
        """Update the charm's status."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            # The charm should be in BlockedStatus with install failed msg
            return  # type: ignore[unreachable]

        if not self.cos_agent_related:
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
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

        # Check health of all exporters
        exporters_health = [
            exporter_helpers.check_exporter_health(exporter, self.model)
            for exporter in self.exporters
        ]

        if all(exporters_health):
            self.model.unit.status = ActiveStatus("Unit is ready")

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            logging.info(  # type: ignore[unreachable]
                "Config changed called before install complete, deferring event: %s",
                event.handle,
            )
            event.defer()

        if self.cos_agent_related:
            success, message = self.validate_configs()
            if not success:
                self.model.unit.status = BlockedStatus(message)
                return

            for exporter in self.exporters:
                exporter_helpers.reconfigure_exporter(exporter, self.model)

        self._on_update_status(event)

    def _on_cos_agent_relation_joined(self, event: EventBase) -> None:
        """Enable and start the exporters when relation joined."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            logger.info(  # type: ignore[unreachable]
                "Defer cos-agent relation join because resources are not ready yet."
            )
            event.defer()
            return

        for exporter in self.exporters:
            exporter.enable_and_start()
            logger.info(f"Enabled and started {exporter.exporter_name} service")

        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporters when relation departed."""

        for exporter in self.exporters:
            exporter.disable_and_stop()
            logger.info(f"Disabled and stopped {exporter.exporter_name} service")

        self._on_update_status(event)

    def get_num_cos_agent_relations(self, relation_name: str) -> int:
        """Get the number of relation given a relation_name."""
        relations = self.model.relations.get(relation_name, [])
        return len(relations)

    def validate_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the charm."""
        exporter_ports = []
        for exporter in self.exporters:
            exporter_ports.append(exporter.port)
            config_valid, config_valid_message = exporter.validate_exporter_configs()
            if not config_valid:
                return config_valid, config_valid_message

        if len(exporter_ports) > len(set(exporter_ports)):
            return False, "Ports must be unique for each exporter."

        return True, "Charm config is valid."

    @property
    def cos_agent_related(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_cos_agent_relations != 0

    @property
    def too_many_cos_agent_relations(self) -> bool:
        """Return True if there're more than one cos-agent relation."""
        return self.num_cos_agent_relations > 1


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
