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

from hw_tools import HWTool, HWToolHelper, get_detected_hw_tools
from service import BaseExporter, ExporterError, HardwareExporter, SmartCtlExporter

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
                {"path": "/metrics", "port": int(self.model.config["hardware-exporter-port"])},
                {"path": "/metrics", "port": int(self.model.config["smartctl-exporter-port"])},
            ],
            # Setting scrape_timeout as collect_timeout in the `duration` format specified in
            # https://prometheus.io/docs/prometheus/latest/configuration/configuration/#duration
            scrape_configs=[{"scrape_timeout": f"{int(self.model.config['collect-timeout'])}s"}],
        )

        self._stored.set_default(
            # resource_installed is a flag that tracks the installation state for
            # the juju resources and also the different exporters
            resource_installed=False,
            detected_hw_tools=[],
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
    def exporters(self) -> List[BaseExporter]:
        """Return list of exporters based on detected hardware."""
        exporters: List[BaseExporter] = []
        detected_hw_tools = self.get_detected_hw_tools_stored()
        if set(detected_hw_tools) & set(HardwareExporter.hw_tools()):
            exporters.append(
                HardwareExporter(
                    self.charm_dir,
                    self.model.config,
                    detected_hw_tools,
                )
            )

        if set(detected_hw_tools) & set(SmartCtlExporter.hw_tools()):
            exporters.append(SmartCtlExporter(self.charm_dir, self.model.config))

        return exporters

    def get_detected_hw_tools_stored(self) -> List[HWTool]:
        """Get hardware tool list from stored or from machine if not present.

        This function store the hardware tools as sting because HWTool object is not accepted on
        Ops framework. However, to return the values it uses HWTool objects.
        """
        if not self._stored.detected_hw_tools:  # type: ignore[truthy-function]
            detected_hw_tools = get_detected_hw_tools()  # type: ignore[unreachable]
            self._stored.detected_hw_tools = [tool.value for tool in detected_hw_tools]
        return [
            HWTool(value) for value in self._stored.detected_hw_tools  # type: ignore[attr-defined]
        ]

    def _on_redetect_hardware(self, event: ops.ActionEvent) -> None:
        """Detect hardware tool list and option to rerun the install hook."""
        stored_detected_hw_tools = self.get_detected_hw_tools_stored()
        current_hw_tools = get_detected_hw_tools()

        hw_change_detected = False
        if stored_detected_hw_tools != current_hw_tools:
            hw_change_detected = True

        result = {
            "hardware-change-detected": hw_change_detected,
            "current-hardware-tools": ",".join(stored_detected_hw_tools),
            "update-hardware-tools": False,
        }
        # Show compare lists if hw_change_detected
        if hw_change_detected:
            result["detected-hardware-tools"] = ",".join(current_hw_tools)

        if event.params["apply"] and hw_change_detected:
            # Reset the value in local Store
            self._stored.detected_hw_tools = current_hw_tools
            event.log(f"Run install hook with enable tools: {','.join(current_hw_tools)}")
            self._on_install_or_upgrade(event=event)
            result["update-hardware-tools"] = True
        event.set_results(result)

    def _on_install_or_upgrade(self, event: EventBase) -> None:
        """Install or upgrade charm."""
        self.model.unit.status = MaintenanceStatus("Installing resources...")

        detected_hw_tools = self.get_detected_hw_tools_stored()

        msg: str
        resource_installed: bool

        # Install hw tools
        resource_installed, msg = self.hw_tool_helper.install(
            self.model.resources, detected_hw_tools
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
            self.get_detected_hw_tools_stored(),
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

        hw_tool_ok, error_msg = self.hw_tool_helper.check_installed(
            self.get_detected_hw_tools_stored()
        )
        if not hw_tool_ok:
            self.model.unit.status = BlockedStatus(error_msg)
            return

        # Check health of all exporters
        exporters_health = [self._check_exporter_health(exporter) for exporter in self.exporters]

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
                success = exporter.render_config()
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

    @property
    def cos_agent_related(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_cos_agent_relations != 0


if __name__ == "__main__":  # pragma: nocover
    ops.main(HardwareObserverCharm)  # type: ignore
