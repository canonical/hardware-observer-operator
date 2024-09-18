"""Config."""

import typing as t
from enum import Enum
from pathlib import Path

from pydantic import BaseModel  # pylint: disable = no-name-in-module


class ExporterSettings(BaseModel):  # pylint: disable = too-few-public-methods
    """Constant settings common across exporters."""

    health_retry_count: int = 3
    health_retry_timeout: int = 3
    service_template: str
    service_path: Path
    name: str
    config_template: str
    config_path: Path


class HardwareExporterSettings(ExporterSettings):  # pylint: disable = too-few-public-methods
    """Constant settings for Hardware Exporter."""

    name: str = "hardware-exporter"
    config_path: Path = Path(f"/etc/{name}-config.yaml")
    service_path: Path = Path(f"/etc/systemd/system/{name}.service")
    config_template: str = f"{name}-config.yaml.j2"
    service_template: str = f"{name}.service.j2"
    crash_msg: str = "Hardware exporter crashed unexpectedly, please refer to systemd logs..."

    redfish_timeout: int = 10
    redfish_max_retry: int = 2


HARDWARE_EXPORTER_SETTINGS = HardwareExporterSettings()


class SmartCtlExporterSettings(ExporterSettings):  # pylint: disable = too-few-public-methods
    """Constant settings for SmartCtl Exporter."""

    name: str = "smartctl-exporter"
    config_path: Path = Path(f"/etc/{name}-config.yaml")
    service_path: Path = Path(f"/etc/systemd/system/{name}.service")
    config_template: str = f"{name}-config.yaml.j2"
    service_template: str = f"{name}.service.j2"
    crash_msg: str = "SmartCtl exporter crashed unexpectedly, please refer to systemd logs..."


SMARTCTL_EXPORTER_SETTINGS = SmartCtlExporterSettings()


class SystemVendor(str, Enum):
    """Different hardware system vendor."""

    DELL = "Dell Inc."
    HP = "HP"
    HPE = "HPE"


class StorageVendor(str, Enum):
    """Hardware Storage vendor."""

    BROADCOM = "Broadcom / LSI"


class HWTool(str, Enum):
    """Tools for RAID."""

    # Storage
    STORCLI = "storcli"
    SSACLI = "ssacli"
    SAS2IRCU = "sas2ircu"
    SAS3IRCU = "sas3ircu"
    PERCCLI = "perccli"
    IPMI_DCMI = "ipmi_dcmi"
    IPMI_SEL = "ipmi_sel"
    IPMI_SENSOR = "ipmi_sensor"
    REDFISH = "redfish"
    SMARTCTL = "smartctl"
    SMARTCTL_EXPORTER = "smartctl_exporter"
    DCGM = "dcgm"


TPR_RESOURCES: t.Dict[HWTool, str] = {
    HWTool.STORCLI: "storcli-deb",
    HWTool.PERCCLI: "perccli-deb",
    HWTool.SAS2IRCU: "sas2ircu-bin",
    HWTool.SAS3IRCU: "sas3ircu-bin",
}

HARDWARE_EXPORTER_COLLECTOR_MAPPING = {
    HWTool.STORCLI: "collector.mega_raid",
    HWTool.PERCCLI: "collector.poweredge_raid",
    HWTool.SAS2IRCU: "collector.lsi_sas_2",
    HWTool.SAS3IRCU: "collector.lsi_sas_3",
    HWTool.SSACLI: "collector.hpe_ssa",
    HWTool.IPMI_DCMI: "collector.ipmi_dcmi",
    HWTool.IPMI_SEL: "collector.ipmi_sel",
    HWTool.IPMI_SENSOR: "collector.ipmi_sensor",
    HWTool.REDFISH: "collector.redfish",
}

TOOLS_DIR = Path("/usr/sbin")

# SNAP environment
SNAP_COMMON = Path(f"/var/snap/{HARDWARE_EXPORTER_SETTINGS.name}/common")
