"""Config."""
import typing as t
from enum import Enum
from pathlib import Path

# Exporter
EXPORTER_NAME = "hardware-exporter"
EXPORTER_CONFIG_PATH = Path(f"/etc/{EXPORTER_NAME}-config.yaml")
EXPORTER_SERVICE_PATH = Path(f"/etc/systemd/system/{EXPORTER_NAME}.service")
EXPORTER_CONFIG_TEMPLATE = f"{EXPORTER_NAME}-config.yaml.j2"
EXPORTER_SERVICE_TEMPLATE = f"{EXPORTER_NAME}.service.j2"


class SystemVendor(str, Enum):
    """Different hardward system vendor."""

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


TPR_RESOURCES: t.Dict[HWTool, str] = {
    HWTool.STORCLI: "storcli-deb",
    HWTool.PERCCLI: "perccli-deb",
    HWTool.SAS2IRCU: "sas2ircu-bin",
    HWTool.SAS3IRCU: "sas3ircu-bin",
}


TOOLS_DIR = Path("/usr/sbin")

# SNAP envionment
SNAP_COMMON = Path(f"/var/snap/{EXPORTER_NAME}/common")
