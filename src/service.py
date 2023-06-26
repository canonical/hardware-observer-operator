"""Exporter service helper."""
from functools import wraps
from logging import getLogger
from pathlib import Path
from typing import Any, Callable, Dict, Set, Tuple

from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader
from ops.framework import EventBase

from config import (
    EXPORTER_CONFIG_PATH,
    EXPORTER_CONFIG_TEMPLATE,
    EXPORTER_NAME,
    EXPORTER_SERVICE_PATH,
    EXPORTER_SERVICE_TEMPLATE,
)

logger = getLogger(__name__)


def check_installed(func: Callable) -> Callable:
    """Ensure exporter service and exporter config is installed before running operations."""

    @wraps(func)
    def wrapper(self: Any, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> Any:
        """Wrap func."""
        config_path = Path(EXPORTER_CONFIG_PATH)
        service_path = Path(EXPORTER_SERVICE_PATH)
        if not config_path.exists() or not service_path.exists():
            logger.error("Exporter is not installed properly.")
            logger.error("Failed to run '%s'", func.__name__)
            return False
        return_value = func(self, *args, **kwargs)
        return return_value

    return wrapper


class ExporterTemplate:
    """Jinja template helper class for exporter."""

    def __init__(self, search_path: Path):
        """Initialize template class."""
        self.environment = Environment(loader=FileSystemLoader(search_path / "templates"))
        self.config_template = self.environment.get_template(EXPORTER_CONFIG_TEMPLATE)
        self.service_template = self.environment.get_template(EXPORTER_SERVICE_TEMPLATE)

    def _install(self, path: Path, content: str) -> bool:
        """Install file."""
        success = True
        try:
            logger.info("Writing file to %s.", path)
            with open(path, "w", encoding="utf-8") as file:
                file.write(content)
        except (NotADirectoryError, PermissionError) as err:
            logger.error(err)
            logger.info("Writing file to %s - Failed.", path)
            success = False
        else:
            logger.info("Writing file to %s - Done.", path)
        return success

    def _uninstall(self, path: Path) -> bool:
        """Uninstall file."""
        success = True
        try:
            logger.info("Removing file '%s'.", path)
            if path.exists():
                path.unlink()
        except PermissionError as err:
            logger.error(err)
            logger.info("Removing file '%s' - Failed.", path)
            success = False
        else:
            logger.info("Removing file '%s' - Done.", path)
        return success

    def render_config(self, port: str, level: str) -> bool:
        """Render and install exporter config file."""
        content = self.config_template.render(PORT=port, LEVEL=level)
        return self._install(EXPORTER_CONFIG_PATH, content)

    def render_service(self, charm_dir: str, config_file: str) -> bool:
        """Render and install exporter service file."""
        content = self.service_template.render(CHARMDIR=charm_dir, CONFIG_FILE=config_file)
        return self._install(EXPORTER_SERVICE_PATH, content)

    def remove_config(self) -> bool:
        """Remove exporter config file."""
        return self._uninstall(EXPORTER_CONFIG_PATH)

    def remove_service(self) -> bool:
        """Remove exporter service file."""
        return self._uninstall(EXPORTER_SERVICE_PATH)


class Exporter(COSAgentProvider):
    """A class representing the exporter and the metric endpoints."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the class."""
        super().__init__(*args, **kwargs)
        self._stored = self._charm._stored
        self._charm_dir = self._charm.charm_dir
        self._template = ExporterTemplate(self._charm_dir)

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_departed, self._on_relation_departed)

    def install(self) -> bool:
        """Install the exporter."""
        logger.info("Installing %s.", EXPORTER_NAME)
        port = self._stored.config.get("exporter-port", "10000")
        level = self._stored.config.get("exporter-log-level", "INFO")
        success = self._template.render_config(port=port, level=level)
        success = self._template.render_service(str(self._charm_dir), str(EXPORTER_CONFIG_PATH))
        if not success:
            logger.error("Failed to installed %s.", EXPORTER_NAME)
            return success
        systemd.daemon_reload()
        logger.info("%s installed.", EXPORTER_NAME)
        return success

    def uninstall(self) -> bool:
        """Uninstall the exporter."""
        logger.info("Uninstalling %s.", EXPORTER_NAME)
        success = self._template.remove_config()
        success = self._template.remove_service()
        if not success:
            logger.error("Failed to uninstall %s.", EXPORTER_NAME)
            return success
        systemd.daemon_reload()
        logger.info("%s uninstalled.", EXPORTER_NAME)
        return success

    @check_installed
    def stop(self) -> None:
        """Stop the exporter daemon."""
        systemd.service_stop(EXPORTER_NAME)

    @check_installed
    def start(self) -> None:
        """Start the exporter daemon."""
        systemd.service_start(EXPORTER_NAME)

    @check_installed
    def restart(self) -> None:
        """Restart the exporter daemon."""
        systemd.service_restart(EXPORTER_NAME)

    @check_installed
    def check_health(self) -> bool:
        """Check if the exporter daemon is healthy or not."""
        return not systemd.service_failed(EXPORTER_NAME)

    @check_installed
    def check_relation(self) -> bool:
        """Check if the required relation is joined.."""
        relation = self.model.get_relation("cos-agent")
        if not relation:
            return False
        return True

    def on_config_changed(self, change_set: Set[str]) -> None:
        """Respond to config change about the exporter."""
        if "exporter-log-level" in change_set:
            logger.info("Detected changes in 'exporter-log-level'")
            port = self._stored.config.get("exporter-port", "10000")
            level = self._stored.config.get("exporter-log-level", "INFO")
            success = self._template.render_config(port=port, level=level)
            if success:
                self.restart()

    def _on_relation_joined(self, event: EventBase) -> None:  # pylint: disable=unused-argument
        """Start the exporter when relation joined."""
        self.start()

    def _on_relation_departed(self, event: EventBase) -> None:  # pylint: disable=unused-argument
        """Remove the exporter when relation departed."""
        self.stop()
