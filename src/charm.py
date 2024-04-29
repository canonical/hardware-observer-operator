#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
from typing import Any, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from ops.framework import EventBase, StoredState
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

import exporter_helpers
from hw_tools import HWToolHelper
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

        self.exporters = []

        hardware_exporter = exporter_helpers.get_exporter(
            HardwareExporter(self.charm_dir, self.model.config)
        )
        if hardware_exporter:
            self.exporters.append(hardware_exporter)

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

        self._on_update_status(event)

    def _on_remove(self, _: EventBase) -> None:
        """Remove everything when charm is being removed."""
        logger.info("Start to remove.")
        # Remove binary tool
        self.hw_tool_helper.remove(self.model.resources)
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

        if self.too_many_cos_agent_relations:
            self.model.unit.status = BlockedStatus("Cannot relate to more than one grafana-agent")
            return

        config_valid, config_valid_message = self.validate_configs()
        if not config_valid:
            self.model.unit.status = BlockedStatus(config_valid_message)
            return

        hw_tool_ok, error_msg = self.hw_tool_helper.check_installed()
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
        """Start the exporter when relation joined."""
        if not self._stored.resource_installed or not any(  # type: ignore[truthy-function]
            [exporter_helpers.get_exporter(exporter) for exporter in self.exporters]
        ):
            logger.info(  # type: ignore[unreachable]
                "Defer cos-agent relation join because exporters or resources are not ready yet."
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
