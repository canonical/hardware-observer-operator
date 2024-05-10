"""Exporter service helper."""

import os
from abc import ABC, abstractmethod
from logging import getLogger
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional, Tuple

from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader
from ops.model import ConfigData
from redfish import redfish_client
from redfish.rest.v1 import InvalidCredentialsError

from config import (
    HARDWARE_EXPORTER_COLLECTOR_MAPPING,
    HARDWARE_EXPORTER_SETTINGS,
    SMARTCTL_EXPORTER_SETTINGS,
    ExporterSettings,
    HWTool,
)
from hardware import get_bmc_address
from hw_tools import SmartCtlExporterStrategy

logger = getLogger(__name__)


class ExporterError(Exception):
    """Custom exception for exporter errors.

    This will cause juju to set the charm in ErrorStatus.
    """


class BaseExporter(ABC):
    """A class representing the exporter and the metric endpoints."""

    # pylint: disable=too-many-instance-attributes

    exporter_config_path: Optional[Path] = None

    def __init__(self, charm_dir: Path, config: ConfigData, settings: ExporterSettings) -> None:
        """Initialize the Exporter class."""
        self.charm_dir = charm_dir

        self.port: int

        self.settings = settings
        self.environment = Environment(loader=FileSystemLoader(charm_dir / "templates"))
        self.service_template = self.environment.get_template(self.settings.service_template)
        self.exporter_service_path = self.settings.service_path
        self.exporter_name = self.settings.name

        self.log_level = str(config["exporter-log-level"])

    @staticmethod
    @abstractmethod
    def hw_tools() -> List[HWTool]:
        """Return list hardware tools to watch."""

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        if not 1 <= self.port <= 65535:
            logger.error("Invalid exporter port: port must be in [1, 65535].")
            return False, "Invalid config: exporter's port"

        allowed_log_level_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in allowed_log_level_choices:
            logger.error(
                "Invalid exporter-log-level: log-level must be in %s (case-insensitive).",
                allowed_log_level_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"
        return True, "Exporter config is valid."

    def resources_exist(self) -> bool:
        """Return true if required resources exist.

        Overwrite this method if there are resources need to be installed.
        """
        return True

    def install_resources(self) -> bool:
        """Install the necessary resources for the exporter service.

        Overwrite this method if there are resources need to be installed.
        """
        logger.debug("No required resources for %s", self.__class__.__name__)
        return True

    def remove_resources(self) -> bool:
        """Remove exporter resources.

        Overwrite this method if there are resources need to be removed.
        """
        return True

    def remove_config(self) -> bool:
        """Remove exporter configuration file."""
        if self.exporter_config_path is not None and self.exporter_config_path.exists():
            return remove_file(self.exporter_config_path)
        return True

    def remove_service(self) -> bool:
        """Remove exporter service file."""
        if self.exporter_service_path.exists():
            return remove_file(self.exporter_service_path)
        return True

    def _restart(self) -> None:
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

    def _render_service(self, params: Dict[str, str]) -> bool:
        """Render and install exporter service file."""
        content = self.service_template.render(**params)
        return write_to_file(self.exporter_service_path, content)

    def render_config(self) -> bool:
        """Render exporter config file.."""
        if self.exporter_config_path is not None:
            content = self._render_config_content()
            return write_to_file(self.exporter_config_path, content, mode=0o600)
        return True

    def _render_config_content(self) -> str:
        """Overwrite this method to render config content."""
        return ""

    def render_service(self) -> bool:
        """Render required files for service."""
        return self._render_service({})

    def verify_render_files_exist(self) -> bool:
        """Verify if service installation is done."""
        config_file_exists = True
        if self.exporter_config_path is not None:
            config_file_exists = self.exporter_config_path.exists()
        service_file_exists = self.exporter_service_path.exists()
        return service_file_exists and config_file_exists

    def install(self) -> bool:
        """Install the exporter."""
        logger.info("Installing %s.", self.exporter_name)

        # Install resources
        install_resource_success = self.install_resources()
        if not install_resource_success:
            logger.error("Failed to install %s resources.", self.exporter_name)
            return False
        if not self.resources_exist():
            logger.error("%s resources are not installed properly.", self.exporter_name)
            # pylint: disable=too-many-instance-attributes
            return False

        # Render config
        render_config_success = self.render_config()
        if not render_config_success:
            logger.error("Failed to render config files for %s.", self.exporter_name)
            return False

        # Install service
        render_service_success = self.render_service()
        if not render_service_success:
            logger.error("Failed to install %s.", self.exporter_name)
            return False

        if not self.verify_render_files_exist():
            logger.error("%s is not installed properly.", self.exporter_name)
            return False

        systemd.daemon_reload()

        logger.info("%s installed.", self.exporter_name)
        return True

    def uninstall(self) -> bool:
        """Uninstall the exporter."""
        logger.info("Uninstalling %s.", self.exporter_name)
        service_removed = self.remove_service()
        config_removed = self.render_config()
        resources_removed = self.remove_resources()
        if not (service_removed and config_removed and resources_removed):
            logger.error("Failed to uninstall %s.", self.exporter_name)
            return False
        systemd.daemon_reload()
        logger.info("%s uninstalled.", self.exporter_name)
        return True

    def restart(self) -> None:
        """Restart exporter service with retry."""
        logger.info("Restarting exporter - %s", self.exporter_name)
        try:
            for i in range(1, self.settings.health_retry_count + 1):
                logger.warning("Restarting exporter - %d retry", i)
                self._restart()
                sleep(self.settings.health_retry_timeout)
                if self.check_active():
                    logger.info("Exporter - %s active after restart.", self.exporter_name)
                    break
            if not self.check_active():
                logger.error("Failed to restart exporter - %s.", self.exporter_name)
                raise ExporterError()
        except Exception as err:  # pylint: disable=W0718
            logger.error("Exporter %s crashed unexpectedly: %s", self.exporter_name, err)
            raise ExporterError() from err


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


class SmartCtlExporter(BaseExporter):
    """A class representing the smartctl exporter and the metric endpoints."""

    required_config: bool = False

    def __init__(self, charm_dir: Path, config: ConfigData) -> None:
        """Initialize the Hardware Exporter class."""
        super().__init__(charm_dir, config, SMARTCTL_EXPORTER_SETTINGS)

        self.port = int(config["smartctl-exporter-port"])
        self.collect_timeout = int(config["collect-timeout"])
        self.log_level = str(config["exporter-log-level"])
        self.strategy = SmartCtlExporterStrategy()

    @staticmethod
    def hw_tools() -> List[HWTool]:
        """Return list hardware tools to watch."""
        return [HWTool.SMARTCTL]

    def install_resources(self) -> bool:
        restart = False
        if self.check_active():
            systemd.service_stop(self.exporter_name)
            restart = True
        self.strategy.install()
        if restart:
            systemd.service_restart(self.exporter_name)
        logger.debug("Finish install resources for %s", self.exporter_name)
        return True

    def resources_exist(self) -> bool:
        return self.strategy.check()

    def remove_resources(self) -> bool:
        self.strategy.remove()
        return True


class HardwareExporter(BaseExporter):
    """A class representing the hardware exporter and the metric endpoints."""

    required_config: bool = True

    def __init__(self, charm_dir: Path, config: ConfigData, enable_hw_tools: List[HWTool]) -> None:
        """Initialize the Hardware Exporter class."""
        super().__init__(charm_dir, config, HARDWARE_EXPORTER_SETTINGS)

        self.config_template = self.environment.get_template(self.settings.config_template)
        self.exporter_config_path = self.settings.config_path
        self.port = int(config["hardware-exporter-port"])

        self.enabled_hw_tool_list = enable_hw_tools

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
            LEVEL=self.log_level,
            COLLECT_TIMEOUT=self.collect_timeout,
            COLLECTORS=collectors,
            REDFISH_ENABLE=self.redfish_conn_params,
            REDFISH_HOST=self.redfish_conn_params.get("host", ""),
            REDFISH_USERNAME=self.redfish_conn_params.get("username", ""),
            REDFISH_PASSWORD=self.redfish_conn_params.get("password", ""),
            REDFISH_CLIENT_TIMEOUT=self.redfish_conn_params.get("timeout", ""),
        )
        return content

    def render_service(self) -> bool:
        """Render required files for service."""
        service_rendered = self._render_service(
            {
                "CHARMDIR": str(self.charm_dir),
                "CONFIG_FILE": str(self.exporter_config_path),
            }
        )
        return service_rendered

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        valid, msg = super().validate_exporter_configs()
        if not valid:
            return valid, msg

        # Note we need to use `is False` because `None` means redfish is not
        # available.
        if self.redfish_conn_params_valid(self.redfish_conn_params) is False:
            logger.error("Invalid redfish credentials.")
            return False, "Invalid config: 'redfish-username' or 'redfish-password'"

        return True, "Exporter config is valid."

    def redfish_conn_params_valid(self, redfish_conn_params: Dict[str, str]) -> Optional[bool]:
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
                timeout=redfish_conn_params.get(
                    "timeout", self.settings.redfish_timeout  # type: ignore
                ),
                max_retry=self.settings.redfish_max_retry,  # type: ignore
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

    def get_redfish_conn_params(self, config: ConfigData) -> Dict[str, Any]:
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
        """Return list hardware tools to watch."""
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
