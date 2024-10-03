"""Exporter service helper."""

import os
import shutil
from abc import ABC, abstractmethod
from logging import getLogger
from pathlib import Path
from time import sleep
from typing import Any, Dict, Optional, Set, Tuple

from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from jinja2 import Environment, FileSystemLoader
from ops.model import ConfigData
from redfish import redfish_client
from redfish.rest.v1 import InvalidCredentialsError

from config import (
    HARDWARE_EXPORTER_COLLECTOR_MAPPING,
    HARDWARE_EXPORTER_SETTINGS,
    ExporterSettings,
    HWTool,
)
from hardware import get_bmc_address
from hw_tools import DCGMExporterStrategy, SmartCtlExporterStrategy, SnapStrategy

logger = getLogger(__name__)


class ExporterError(Exception):
    """Custom exception for exporter errors.

    This will cause juju to set the charm in ErrorStatus.
    """


class BaseExporter(ABC):
    """A class representing the exporter and the metric endpoints."""

    config: ConfigData
    exporter_name: str
    port: int
    log_level: str

    @staticmethod
    @abstractmethod
    def hw_tools() -> Set[HWTool]:
        """Return hardware tools to watch."""

    @abstractmethod
    def install(self) -> bool:
        """Install the exporter."""

    @abstractmethod
    def uninstall(self) -> bool:
        """Uninstall the exporter."""

    @abstractmethod
    def check_health(self) -> bool:
        """Check if the exporter daemon is healthy or not."""

    @abstractmethod
    def restart(self) -> None:
        """Restart exporter service with retry."""

    @abstractmethod
    def enable_and_start(self) -> None:
        """Enable and start the exporter services."""

    @abstractmethod
    def disable_and_stop(self) -> None:
        """Disable and stop the exporter services."""

    @abstractmethod
    def configure(self) -> bool:
        """Set exporter config."""

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        if not 1 <= self.port <= 65535:
            logger.error("Invalid exporter port: port must be in [1, 65535].")
            return False, "Invalid config: exporter's port"

        return True, "Exporter config is valid."


class RenderableExporter(BaseExporter):
    """A class representing an exporter that needs to render its configuration."""

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

    def configure(self) -> bool:
        """Configure the exporter by rendering templates."""
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
        configure_success = self.configure()
        if not configure_success:
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
        config_removed = self.remove_config()
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

    def validate_exporter_configs(self) -> Tuple[bool, str]:
        """Validate the static and runtime config options for the exporter."""
        valid, msg = super().validate_exporter_configs()
        if not valid:
            return valid, msg

        allowed_log_level_choices = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in allowed_log_level_choices:
            logger.error(
                "Invalid exporter-log-level: log-level must be in %s (case-insensitive).",
                allowed_log_level_choices,
            )
            return False, "Invalid config: 'exporter-log-level'"
        return True, "Exporter config is valid."


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


class SnapExporter(BaseExporter):
    """A class representing a snap exporter."""

    exporter_name: str
    channel: str
    port: int
    strategy: SnapStrategy

    def __init__(self, config: ConfigData):
        """Init."""
        self.config = config

    @property
    def snap_client(self) -> snap.Snap:
        """Return the snap client."""
        return snap.SnapCache()[self.strategy.snap]

    @staticmethod
    def hw_tools() -> Set[HWTool]:
        """Return hardware tools to watch."""
        return set()

    def install(self) -> bool:
        """Install the snap from a channel.

        Returns true if the install is successful, false otherwise.
        """
        try:
            self.strategy.install()
            self.enable_and_start()
            return self.snap_client.present is True
        except Exception:  # pylint: disable=broad-except
            return False

    def uninstall(self) -> bool:
        """Uninstall the snap.

        Returns true if the uninstall is successful, false otherwise.
        """
        try:
            self.strategy.remove()

        # using the snap.SnapError will result into:
        # TypeError: catching classes that do not inherit from BaseException is not allowed
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Failed to remove %s: %s", self.strategy.snap, err)
            return False

        return self.snap_client.present is False

    def enable_and_start(self) -> None:
        """Enable and start the exporter services."""
        self.snap_client.start(list(self.snap_client.services.keys()), enable=True)

    def disable_and_stop(self) -> None:
        """Disable and stop the services."""
        self.snap_client.stop(list(self.snap_client.services.keys()), disable=True)

    def restart(self) -> None:
        """Restart the exporter daemon."""
        self.snap_client.restart(reload=True)

    def set(self, snap_config: dict) -> bool:
        """Set config options for the snap service.

        Return true if successfully updated snap config, otherwise false.
        """
        try:
            self.snap_client.set(snap_config, typed=True)
        except snap.SnapError as err:
            logger.error("Failed to update snap configs %s: %s", self.strategy.snap, err)
            return False
        return True

    def check_health(self) -> bool:
        """Check if all services are active.

        Returns true if the service is healthy, false otherwise.
        """
        return self.strategy.check()

    def configure(self) -> bool:
        """Set the necessary exporter configurations or change snap channel.

        Returns true if the configure is successful, false otherwise.
        """
        return self.install()


class DCGMExporter(SnapExporter):
    """A class representing the DCGM exporter and the metric endpoints."""

    exporter_name: str = "dcgm"
    port: int = 9400
    snap_common: Path = Path("/var/snap/dcgm/common/")
    metric_config: str = "dcgm-exporter-metrics-file"

    def __init__(self, charm_dir: Path, config: ConfigData):
        """Init."""
        self.strategy = DCGMExporterStrategy(str(config["dcgm-snap-channel"]))
        self.charm_dir = charm_dir
        self.metrics_file = self.charm_dir / "src/gpu_metrics/dcgm_metrics.csv"
        self.metric_config_value = self.metrics_file.name
        super().__init__(config)

    def install(self) -> bool:
        """Install the DCGM exporter and configure custom metrics."""
        if not super().install():
            return False

        logger.info("Creating a custom metrics file and configuring the DCGM snap to use it")
        try:
            shutil.copy(self.metrics_file, self.snap_common)
            self.snap_client.set({self.metric_config: self.metric_config_value})
            self.snap_client.restart(reload=True)
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Failed to configure custom DCGM metrics: %s", err)
            return False

        return True

    @staticmethod
    def hw_tools() -> Set[HWTool]:
        """Return hardware tools to watch."""
        return {HWTool.DCGM}


class SmartCtlExporter(SnapExporter):
    """A class representing the smartctl exporter and the metric endpoints."""

    exporter_name: str = "smartctl-exporter"

    def __init__(self, config: ConfigData) -> None:
        """Initialize the SmartctlExporter class."""
        self.port = int(config["smartctl-exporter-port"])
        self.log_level = str(config["exporter-log-level"])
        self.strategy = SmartCtlExporterStrategy(str(config["smartctl-exporter-snap-channel"]))
        super().__init__(config)

    @staticmethod
    def hw_tools() -> Set[HWTool]:
        """Return hardware tools to watch."""
        return {HWTool.SMARTCTL_EXPORTER}

    def configure(self) -> bool:
        """Set the necessary exporter configurations or change snap channel."""
        return super().configure() and self.set(
            {
                "log.level": self.log_level.lower(),
                "web.listen-address": f":{self.port}",
            }
        )


class HardwareExporter(RenderableExporter):
    """A class representing the hardware exporter and the metric endpoints."""

    required_config: bool = True

    def __init__(self, charm_dir: Path, config: ConfigData, available_tools: Set[HWTool]) -> None:
        """Initialize the Hardware Exporter class."""
        super().__init__(charm_dir, config, HARDWARE_EXPORTER_SETTINGS)

        self.config_template = self.environment.get_template(self.settings.config_template)
        self.exporter_config_path = self.settings.config_path
        self.port = int(config["hardware-exporter-port"])
        self.config = config
        self.available_tools = available_tools
        self.collect_timeout = int(config["collect-timeout"])
        self.bmc_address = get_bmc_address()

    def _render_config_content(self) -> str:
        """Render and install exporter config file."""
        collectors = set()
        for tool in self.enabled_tools:
            collector = HARDWARE_EXPORTER_COLLECTOR_MAPPING.get(tool)
            if collector is not None:
                collectors.add(collector)
        content = self.config_template.render(
            PORT=self.port,
            LEVEL=self.log_level,
            COLLECT_TIMEOUT=self.collect_timeout,
            COLLECTORS=collectors,
            REDFISH_ENABLE=HWTool.REDFISH in self.enabled_tools,
            REDFISH_HOST=self.redfish_conn_params.get("host", ""),
            REDFISH_USERNAME=self.redfish_conn_params.get("username", ""),
            REDFISH_PASSWORD=self.redfish_conn_params.get("password", ""),
            REDFISH_CLIENT_TIMEOUT=self.redfish_conn_params.get("timeout", ""),
        )
        return content

    @property
    def enabled_tools(self) -> Set[HWTool]:
        """Get the enabled hardware tools.

        Tools that are available, but disabled should not be used on prometheus hardware exporter.
        """
        enabled_tools = self.available_tools.copy()
        if self.config["redfish-disable"]:
            enabled_tools.discard(HWTool.REDFISH)
        return enabled_tools

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

        if HWTool.REDFISH in self.enabled_tools and self.redfish_conn_params_valid() is False:
            logger.error("Invalid redfish credentials.")
            return False, "Invalid config: 'redfish-username' or 'redfish-password'"

        return True, "Exporter config is valid."

    def redfish_conn_params_valid(self) -> bool:
        """Check if redfish connections parameters is valid or not.

        Verifies the connection parameters if redfish is enabled. If the redfish connection
        parameters are valid, it returns True; if not valid, it returns False.
        """
        if not (
            self.redfish_conn_params.get("username", "")
            and self.redfish_conn_params.get("password", "")
        ):
            logger.warning("Empty redfish username/password, skip validation.")
            return False

        redfish_obj = None
        try:
            redfish_obj = redfish_client(
                base_url=self.redfish_conn_params.get("host", ""),
                username=self.redfish_conn_params.get("username", ""),
                password=self.redfish_conn_params.get("password", ""),
                timeout=self.redfish_conn_params.get(
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

    @property
    def redfish_conn_params(self) -> Dict[str, Any]:
        """Get redfish connection parameters."""
        return {
            "host": f"https://{self.bmc_address}",
            "username": self.config["redfish-username"],
            "password": self.config["redfish-password"],
            "timeout": self.config["collect-timeout"],
        }

    @staticmethod
    def hw_tools() -> Set[HWTool]:
        """Return hardware tools to watch."""
        return {
            HWTool.STORCLI,
            HWTool.SSACLI,
            HWTool.SAS2IRCU,
            HWTool.SAS3IRCU,
            HWTool.PERCCLI,
            HWTool.IPMI_DCMI,
            HWTool.IPMI_SEL,
            HWTool.IPMI_SENSOR,
            HWTool.REDFISH,
        }
