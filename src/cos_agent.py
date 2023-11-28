"""COS relation handler."""
from logging import getLogger
from typing import Any, Dict, List, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

from config import EXPORTER_RELATION_NAME
from hardware import validate_redfish_credential
from service import Exporter

logger = getLogger(__name__)


class Handler(ops.Object):
    """A class representing the cos-agent relation handler."""

    def __init__(
        self,
        charm: ops.CharmBase,
        exporter: Exporter,
        metrics_endpoints: List[Dict[str, object]],
        relation_name: str = EXPORTER_RELATION_NAME,
    ) -> None:
        """Initialize the class."""
        super().__init__(charm, relation_name)
        self.charm = charm
        self.exporter = exporter
        self.num_relations = self.get_num_relations(relation_name)
        self.cos_exporter_provider = COSAgentProvider(
            self.charm,
            relation_name=relation_name,
            metrics_endpoints=metrics_endpoints,
        )

        self.charm.framework.observe(
            self.charm.on[relation_name].relation_joined,
            self._on_exporter_relation_joined,
        )
        self.charm.framework.observe(
            self.charm.on[relation_name].relation_departed,
            self._on_exporter_relation_departed,
        )

    def _on_exporter_relation_joined(self, _: ops.EventBase) -> None:
        """Start the exporter when relation joined."""
        self.exporter.start()

    def _on_exporter_relation_departed(self, _: ops.EventBase) -> None:
        """Remove the exporter when relation departed."""
        self.exporter.stop()

    @property
    def exporter_enabled(self) -> bool:
        """Return True if cos-agent relation is present."""
        return self.num_relations != 0

    @property
    def exporter_online(self) -> bool:
        """Return True if the exporter is online."""
        return self.exporter.check_health()

    @property
    def too_many_relations(self) -> bool:
        """Return True if there're more than one cos-agent relation."""
        return self.num_relations > 1

    def get_num_relations(self, relation_name: str) -> int:
        """Get the number of relation given a relation_name."""
        relations = self.charm.model.relations.get(relation_name, [])
        return len(relations)

    def install_exporter(self) -> bool:
        """Install the exporter."""
        return self.exporter.install()

    def uninstall_exporter(self) -> bool:
        """Uninstall the exporter."""
        return self.exporter.uninstall()

    def configure_exporter(self, options: Dict[str, Any], change_set: set) -> bool:
        """Configure the exporter."""
        if not self.exporter.config_options.intersection(change_set):
            logger.info("No changes in exporter config.")
            return True

        logger.info("Detected changes in exporter config.")
        return self.exporter.configure(**options)

    def validate_exporter_configs(self, options: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        port = int(options.get("port", 0))
        if not 1 <= port <= 65535:
            logger.error("Invalid exporter-port: port must be in [1, 65535].")
            return False, "Invalid config: 'exporter-port'"

        level = options.get("level", "")
        allowed_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level.upper() not in allowed_choices:
            logger.error(
                "Invalid exporter-log-level: level must be in %s (case-insensitive).",
                allowed_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"

        valid = True
        redfish_options = options.get("redfish_options")
        if redfish_options and redfish_options.get("enable"):
            valid = validate_redfish_credential(
                redfish_options.get("host", ""),
                username=redfish_options.get("username", ""),
                password=redfish_options.get("password", ""),
            )
        if not valid:
            logger.error("Invalid redfish-username or redfish-password")
            logger.error("Please also check if redfish is available on the server.")
            return False, "Invalid redfish credential or redfish is not available."

        return True, "Exporter config is valid."
