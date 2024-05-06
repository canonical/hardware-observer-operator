"""Exporter service helper."""

import os
from abc import ABC, abstractmethod
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader
from redfish import redfish_client
from redfish.rest.v1 import InvalidCredentialsError

from config import (
    HARDWARE_EXPORTER_COLLECTOR_MAPPING,
    ExporterSettings,
    HARDWARE_EXPORTER_SETTINGS,
)
from hardware import get_bmc_address
from hw_tools import bmc_hw_verifier, HWTool

logger = getLogger(__name__)


class ExporterError(Exception):
    """Custom exception for exporter errors.

    This will cause juju to set the charm in ErrorStatus.
    """


class BaseExporter(ABC):
    """A class representing the exporter and the metric endpoints."""

    def __init__(self, charm_dir: Path, config: Dict, settings: ExporterSettings) -> None:
        """Initialize the Exporter class."""
        self.charm_dir = charm_dir

        self.port: int

        self.settings = settings
        self.environment = Environment(loader=FileSystemLoader(charm_dir / "templates"))
        self.config_template = self.environment.get_template(self.settings.config_template)
        self.service_template = self.environment.get_template(self.settings.service_template)
        self.exporter_service_path = self.settings.service_path
        self.exporter_config_path = self.settings.config_path
        self.exporter_name = self.settings.name

        self.level = str(config["exporter-log-level"])

    def render_service(self, charm_dir: str, config_file: str) -> bool:
        """Render and install exporter service file."""
        content = self.service_template.render(CHARMDIR=charm_dir, CONFIG_FILE=config_file)
        return write_to_file(self.exporter_service_path, content)

    def render_config(self):
        """Render and install exporter config file."""
        content = self._render_config_content()
        return write_to_file(self.exporter_config_path, content, mode=0o600)

    @abstractmethod
    def _render_config_content(self) -> str:
        """Render config file content."""

    @abstractmethod
    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""

    def remove_config(self) -> bool:
        """Remove exporter config file."""
        return remove_file(self.exporter_config_path)

    def remove_service(self) -> bool:
        """Remove exporter service file."""
        return remove_file(self.exporter_service_path)

    def restart(self) -> None:
        """Restart the exporter daemon."""
        systemd.service_restart(self.exporter_name)

    def enable_and_start(self) -> None:
        """Enable and start the exporter service."""
        systemd.service_enable(self.exporter_name)
        systemd.service_start(self.exporter_name)

    def disable_and_stop(self) -> None:
        """Disable and stop the exporter service."""
        systemd.service_disable(self.exporter_name)
        systemd.service_stop(self.exporter_name)

    def check_active(self) -> bool:
        """Check if the exporter is active or not."""
        return systemd.service_running(self.exporter_name)

    def check_health(self) -> bool:
        """Check if the exporter daemon is healthy or not."""
        return not systemd.service_failed(self.exporter_name)

    def install(self) -> bool:
        """Install the exporter."""
        logger.info("Installing %s.", self.exporter_name)
        config_success = self.render_config()
        service_success = self.render_service(str(self.charm_dir), str(self.exporter_config_path))
        if not (config_success and service_success):
            logger.error("Failed to install %s.", self.exporter_name)
            return False
        systemd.daemon_reload()

        # Verify installed
        if not (self.exporter_config_path.exists() and self.exporter_service_path.exists()):
            logger.error(f"{self.exporter_name} is not installed properly.")
            return False

        logger.info("%s installed.", self.exporter_name)
        return True

    def uninstall(self) -> bool:
        """Uninstall the exporter."""
        logger.info("Uninstalling %s.", self.exporter_name)
        config_success = self.remove_config()
        service_success = self.remove_service()
        if not (config_success and service_success):
            logger.error("Failed to uninstall %s.", self.exporter_name)
            return False
        systemd.daemon_reload()
        logger.info("%s uninstalled.", self.exporter_name)
        return True


def write_to_file(path: Path, content: str, mode: Optional[int] = None) -> bool:
    """Write to file with provided content."""
    success = True
    try:
        logger.info("Writing file to %s.", path)
        fileobj = (
            os.fdopen(os.open(path, os.O_CREAT | os.O_WRONLY, mode), "w", encoding="utf-8")
            if mode
            # create file with default permissions based on default OS umask
            else open(path, "w", encoding="utf-8")  # pylint: disable=consider-using-with
        )
        with fileobj as file:
            file.write(content)
    except (NotADirectoryError, PermissionError) as err:
        logger.error(err)
        logger.info("Writing file to %s - Failed.", path)
        success = False
    else:
        logger.info("Writing file to %s - Done.", path)
    return success


def remove_file(path: Path) -> bool:
    """Remove file."""
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


class HardwareExporter(BaseExporter):
    """A class representing the hardware exporter and the metric endpoints."""

    def __init__(self, charm_dir: Path, config: Dict, enabled_hw_tool_list_values: List) -> None:
        """Initialize the Hardware Exporter class."""
        super().__init__(charm_dir, config, HARDWARE_EXPORTER_SETTINGS)

        self.port = int(config["hardware-exporter-port"])

        self.enabled_hw_tool_list = [HWTool(value) for value in enabled_hw_tool_list_values]

        self.redfish_conn_params = self.get_redfish_conn_params(config)
        self.collect_timeout = int(config["collect-timeout"])

    def _render_config_content(self) -> str:
        """Render and install exporter config file."""
        collectors = []
        for tool in self.enabled_hw_tool_list:
            collector = HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(tool)
            if collector is not None:
                collectors += collector
        content = self.config_template.render(
            PORT=self.port,
            LEVEL=self.level,
            COLLECT_TIMEOUT=self.collect_timeout,
            COLLECTORS=collectors,
            REDFISH_ENABLE=self.redfish_conn_params != {},
            REDFISH_HOST=self.redfish_conn_params.get("host", ""),
            REDFISH_USERNAME=self.redfish_conn_params.get("username", ""),
            REDFISH_PASSWORD=self.redfish_conn_params.get("password", ""),
            REDFISH_CLIENT_TIMEOUT=self.redfish_conn_params.get("timeout", ""),
        )
        return content

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        if not 1 <= self.port <= 65535:
            logger.error("Invalid hardware-exporter-port: port must be in [1, 65535].")
            return False, "Invalid config: 'hardware-exporter-port'"

        allowed_level_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.level.upper() not in allowed_level_choices:
            logger.error(
                "Invalid exporter-log-level: level must be in %s (case-insensitive).",
                allowed_level_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"

        # Note we need to use `is False` because `None` means redfish is not
        # available.
        if self.redfish_conn_params_valid(self.redfish_conn_params) is False:
            logger.error("Invalid redfish credentials.")
            return False, "Invalid config: 'redfish-username' or 'redfish-password'"

        return True, "Exporter config is valid."

    def redfish_conn_params_valid(self, redfish_conn_params) -> Optional[bool]:
        """Check if redfish connections parameters is valid or not.

        If the redfish connection params is not available this property returns
        None. Otherwise, it verifies the connection parameters. If the redfish
        connection parameters are valid, it returns True; if not valid, it
        returns False.
        """
        if not redfish_conn_params:
            return None

        redfish_obj = None
        try:
            redfish_obj = redfish_client(
                base_url=redfish_conn_params.get("host", ""),
                username=redfish_conn_params.get("username", ""),
                password=redfish_conn_params.get("password", ""),
                timeout=redfish_conn_params.get("timeout", self.settings.redfish_timeout),
                max_retry=self.settings.redfish_max_retry,
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

    def get_redfish_conn_params(self, config) -> Dict[str, Any]:
        """Get redfish connection parameters if redfish is available."""
        if HWTool.REDFISH not in self.enabled_hw_tool_list:
            logger.warning("Redfish unavailable, disregarding redfish config options...")
            return {}
        return {
            "host": f"https://{get_bmc_address()}",
            "username": config["redfish-username"],
            "password": config["redfish-password"],
            "timeout": config["collect-timeout"],
        }

    @staticmethod
    def hw_tools() -> List[HWTool]:
        """Return list of hw tools to watch."""
        return [
            HWTool.STORCLI,
            HWTool.SSACLI,
            HWTool.SAS2IRCU,
            HWTool.SAS3IRCU,
            HWTool.PERCCLI,
            HWTool.IPMI_DCMI,
            HWTool.IPMI_SEL,
            HWTool.IPMI_SENSOR,
            HWTool.REDFISH,
        ]
