#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, Dict, List, Set, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from hw_tools import HWTool, HWToolHelper, detect_available_tools, remove_legacy_smartctl_exporter
from service import BaseExporter, DCGMExporter, ExporterError, HardwareExporter, SmartCtlExporter

logger = logging.getLogger(__name__)


class HardwareObserverCharm(ops.CharmBase):
    """Charm the application."""

    _stored = StoredState()

    def __init__(self, *args: Any) -> None:
        """Init."""
        super().__init__(*args)
        self.hw_tool_helper = HWToolHelper()

        self._stored.set_default(
            # resource_installed is a flag that tracks the installation state for
            # the juju resources and also the different exporters
            resource_installed=False,
            stored_tools=set(),
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

        # Add refresh_events to COSAgentProvider to update relation data when
        # config changed (default behavior) and upgrade charm. This is useful
        # for updating alert rules.
        self.cos_agent_provider = COSAgentProvider(
            self,
            refresh_events=[self.on.config_changed, self.on.upgrade_charm],
            scrape_configs=self._scrape_config,
            dashboard_dirs=self._dashboards(),
        )

        self.num_cos_agent_relations = self.get_num_cos_agent_relations("cos-agent")

    @property
    def exporters(self) -> List[BaseExporter]:
        """Return list of exporters based on detected hardware."""
        exporters: List[BaseExporter] = []
        stored_tools = self.stored_tools
        if stored_tools & HardwareExporter.hw_tools():
            exporters.append(
                HardwareExporter(
                    self.charm_dir,
                    self.model.config,
                    stored_tools,
                )
            )

        if stored_tools & SmartCtlExporter.hw_tools():
            exporters.append(SmartCtlExporter(self.model.config))

        if stored_tools & DCGMExporter.hw_tools():
            exporters.append(DCGMExporter(self.model.config))

        return exporters

    @property
    def stored_tools(self) -> Set[HWTool]:
        """Get the current hardware tools from stored or from machine if not present.

        Since StoredState cannot store arbitrary objects, re-instantiate tools from tool names.
        """
        if not self._stored.stored_tools:  # type: ignore[truthy-function]
            self._stored.stored_tools = {  # type: ignore[unreachable]
                tool.value for tool in detect_available_tools()
            }
        # remove legacy smartctl tool if present
        # See https://github.com/canonical/hardware-observer-operator/pull/327
        self._stored.stored_tools.discard("smartctl")  # type: ignore[attr-defined]
        return {HWTool(value) for value in self._stored.stored_tools}  # type: ignore[attr-defined]

    @stored_tools.setter
    def stored_tools(self, tools: Set[HWTool]) -> None:
        """Record the tools via StoredState.

        StoredState cannot store arbitrary objects so we convert Set[HWTool] into Set[str].
        This is reversible by re-instantiating tools from tool names.
        """
        self._stored.stored_tools = {tool.value for tool in tools}

    def _on_redetect_hardware(self, event: ops.ActionEvent) -> None:
        """Redetect available hardware tools and option to rerun the install hook."""
        available_tools = detect_available_tools()

        hw_change_detected = self.stored_tools != available_tools

        sorted_stored_tools = ",".join(map(lambda member: member.value, sorted(self.stored_tools)))
        sorted_available_tools = ",".join(
            map(lambda member: member.value, sorted(available_tools))
        )

        if event.params["apply"] and hw_change_detected:
            # Update the value in local Store
            self.stored_tools = available_tools
            event.log(f"Run install hook with enable tools: {sorted_available_tools}")
            self._on_install_or_upgrade(event=event)

        result = {
            "hardware-change-detected": hw_change_detected,
            "current-hardware-tools": sorted_stored_tools,
            "update-hardware-tools": bool(event.params["apply"] and hw_change_detected),
            "detected-hardware-tools": sorted_available_tools if hw_change_detected else "",
        }

        event.set_results(result)

    def _on_install_or_upgrade(self, event: EventBase) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")

        remove_legacy_smartctl_exporter()

        msg: str
        resource_installed: bool

        # Install hw tools
        resource_installed, msg = self.hw_tool_helper.install(
            self.model.resources, self.stored_tools
        )

        self._stored.resource_installed = resource_installed
        if not resource_installed:
            logger.warning(msg)
            self.model.unit.status = BlockedStatus(msg)
            return

        # Install exporter services and resources
        for exporter in self.exporters:
            exporter_install_ok = exporter.install()
            if not exporter_install_ok:
                resource_installed = False
                self._stored.resource_installed = resource_installed
                msg = f"Exporter {exporter.exporter_name} install failed"
                logger.warning(msg)
                self.model.unit.status = BlockedStatus(msg)
                return

        self._on_update_status(event)

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.hw_tool_helper.remove(
            self.model.resources,
            self.stored_tools,
        )
        self._stored.resource_installed = False

        # Remove exporters
        for exporter in self.exporters:
            self.model.unit.status = MaintenanceStatus(f"Removing {exporter.exporter_name}...")
            exporter.uninstall()

    def _on_update_status(self, _: EventBase) -> None:  # noqa: C901
        """Update the charm's status."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            # The charm should be in BlockedStatus with install failed msg
            return  # type: ignore[unreachable]

        if not self.cos_agent_related:
            self.model.unit.status = BlockedStatus("Missing relation: [cos-agent]")
            return

        for exporter in self.exporters:
            config_valid, config_valid_message = exporter.validate_exporter_configs()
            if not config_valid:
                self.model.unit.status = BlockedStatus(config_valid_message)
                return

        hw_tool_ok, error_msg = self.hw_tool_helper.check_installed(self.stored_tools)
        if not hw_tool_ok:
            self.model.unit.status = BlockedStatus(error_msg)
            return

        # Check health of all exporters
        exporters_health = [self._check_exporter_health(exporter) for exporter in self.exporters]

        # If this correction failed, the charm will be set in error status
        self.hw_tool_helper.correct_storelib_log_permissions()

        if all(exporters_health):
            self.model.unit.status = ActiveStatus("Unit is ready")

    def _check_exporter_health(self, exporter: BaseExporter) -> bool:
        """Check exporter health."""
        if not exporter.check_health():
            logger.warning("%s - Exporter health check failed.", exporter.exporter_name)
            try:
                exporter.restart()
            except ExporterError as e:
                msg = f"Exporter {exporter.exporter_name} crashed unexpectedly: {e}"
                logger.error(msg)
                # Setting the status as blocked instead of error
                # since other exporters may still be healthy.
                self.model.unit.status = BlockedStatus(msg)
                return False
        return True

    def _on_config_changed(self, event: EventBase) -> None:
        """Reconfigure charm."""
        if not self._stored.resource_installed:  # type: ignore[truthy-function]
            logger.info(  # type: ignore[unreachable]
                "Config changed called before install complete, deferring event: %s",
                event.handle,
            )
            event.defer()
            return

        if self.cos_agent_related:
            success, message = self.validate_configs()
            if not success:
                self.model.unit.status = BlockedStatus(message)
                return
            for exporter in self.exporters:
                success = exporter.configure()
                if success:
                    exporter.restart()
                else:
                    message = (
                        f"Failed to configure {exporter.exporter_name}, "
                        "please check if the server is healthy."
                    )
                    self.model.unit.status = BlockedStatus(message)

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
            logger.info("Enabled and started %s service", exporter.exporter_name)

        self._on_update_status(event)

    def _on_cos_agent_relation_departed(self, event: EventBase) -> None:
        """Remove the exporters when relation departed."""
        for exporter in self.exporters:
            exporter.disable_and_stop()
            logger.info("Disabled and stopped %s service", exporter.exporter_name)

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

    def _scrape_config(self) -> List[Dict[str, Any]]:
        """Generate the scrape config as needed."""
        # Setting scrape_timeout as collect_timeout in the `duration` format specified in
        # https://prometheus.io/docs/prometheus/latest/configuration/configuration/#duration
        scrape_config: List[Dict[str, Any]] = []
        timeout = f"{self.model.config['collect-timeout']}s"

        for exporter in self.exporters:
            if isinstance(exporter, HardwareExporter):
                port = self.model.config["hardware-exporter-port"]
                scrape_config.append(
                    {
                        "metrics_path": "/metrics",
                        "static_configs": [{"targets": [f"localhost:{port}"]}],
                        "scrape_timeout": timeout,
                    }
                )
            if isinstance(exporter, SmartCtlExporter):
                port = self.model.config["smartctl-exporter-port"]
                scrape_config.append(
                    {
                        "metrics_path": "/metrics",
                        "static_configs": [{"targets": [f"localhost:{port}"]}],
                        "scrape_timeout": timeout,
                    }
                )
            if isinstance(exporter, DCGMExporter):
                port = 9400
                scrape_config.append(
                    {
                        "metrics_path": "/metrics",
                        "static_configs": [{"targets": [f"localhost:{port}"]}],
                        "scrape_timeout": timeout,
                    }
                )
        return scrape_config

    def _dashboards(self) -> List[str]:
        """Create the dashboards as needed."""
        dashboards = []
        for exporter in self.exporters:
            if isinstance(exporter, HardwareExporter):
                dashboards.append("./src/dashboards_hardware_exporter")
            if isinstance(exporter, SmartCtlExporter):
                dashboards.append("./src/dashboards_smart_ctl")
            if isinstance(exporter, DCGMExporter):
                dashboards.append("./src/dashboards_dcgm")
        return dashboards

    @property
    def cos_agent_related(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_cos_agent_relations != 0


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)
