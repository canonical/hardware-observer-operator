"""Config."""

import typing as t
from enum import Enum
from pathlib import Path

import pydantic

DEFAULT_BIND_ADDRESS = "127.0.0.1"


class ExporterSettings(pydantic.BaseModel):  # pylint: disable = too-few-public-methods
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
    SMARTCTL_EXPORTER = "smartctl-exporter"
    DCGM = "dcgm"
    NVIDIA_DRIVER = "nvidia-driver"


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

class DcgmConfig(pydantic.BaseModel):
    channel: str = pydantic.Field("")

    @pydantic.validator("channel")
    def validate_channel(cls, value):
        if value == "":
            return value

        try:
            track, risk = value.split("/", 1)
        except ValueError:
            raise ValueError('Channel must be in the form "<track>/<risk>"')

        valid_tracks = {"v3", "v4-cuda11", "v4-cuda12", "v4-cuda13"}
        valid_risks = {"stable", "edge", "candidate"}

        if track not in valid_tracks:
            raise ValueError(f'Invalid track "{track}". Must be one of {sorted(valid_tracks)}')
        if risk not in valid_risks:
            raise ValueError(f'Invalid channel risk "{risk}". Must be one of {sorted(valid_risks)}')

        return value
