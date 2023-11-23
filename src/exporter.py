"""Exporter relation observer."""
from logging import getLogger
from typing import Any, Dict, Tuple

import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

from config import EXPORTER_RELATION_NAME
from hardware import validate_redfish_credential
from service import Exporter

logger = getLogger(__name__)


class Observer(ops.Object):
    """A class representing the exporter relation observer."""

    agent_configs = {
        "exporter-port",
        "exporter-log-level",
        "redfish-host",
        "redfish-username",
        "redfish-password",
    }

    def __init__(self, charm: ops.CharmBase) -> None:
        """Initialize the class."""
        super().__init__(charm, EXPORTER_RELATION_NAME)
        self.charm = charm
        self.agent = Exporter(charm.charm_dir)
        self.num_relations = self.get_num_relations(EXPORTER_RELATION_NAME)
        self.cos_agent_provider = COSAgentProvider(
            self.charm,
            relation_name=EXPORTER_RELATION_NAME,
            metrics_endpoints=[
                {
                    "path": "/metrics",
                    "port": int(
                        self.charm.model.config["exporter-port"],
                    ),
                }
            ],
        )

        self.charm.framework.observe(
            self.charm.on[EXPORTER_RELATION_NAME].relation_joined,
            self._on_agent_relation_joined,
        )
        self.charm.framework.observe(
            self.charm.on[EXPORTER_RELATION_NAME].relation_departed,
            self._on_agent_relation_departed,
        )

    def _on_agent_relation_joined(self, _: ops.EventBase) -> None:
        """Start the agent when relation joined."""
        self.agent.start()
        # self.charm.update_status(event)

    def _on_agent_relation_departed(self, _: ops.EventBase) -> None:
        """Remove the agent when relation departed."""
        self.agent.stop()
        # self.charm.update_status(event)

    @property
    def agent_enabled(self) -> bool:
        """Return True if cos-agent relation is not zero."""
        return self.num_relations != 0

    @property
    def agent_online(self) -> bool:
        """Return True if the exporter agent is online."""
        return self.agent.check_health()

    @property
    def too_many_relations(self) -> bool:
        """Return True if there're more than one cos-agent relation."""
        return self.num_relations > 1

    def get_num_relations(self, relation_name: str) -> int:
        """Get the number of relation given a relation_name."""
        relations = self.charm.model.relations.get(relation_name, [])
        return len(relations)

    def install_agent(self) -> bool:
        """Install the exporter agent."""
        success = self.agent.install()
        return success

    def uninstall_agent(self) -> bool:
        """Uninstall the exporter agent."""
        success = self.agent.uninstall()
        return success

    def configure_agent(self, options: Dict[str, Any], change_set: set) -> bool:
        """Configure the exporter agent."""
        if not self.agent_configs.intersection(change_set):
            logger.info("No changes in exporter config.")
            return True

        logger.info("Detected changes in exporter config.")
        success = self.agent.template.render_config(**options)
        if not success:
            return False

        self.agent.restart()
        return True

    def validate_agent_configs(self, options: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate exporter static and runtime config options."""
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
