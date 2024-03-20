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
EXPORTER_HEALTH_RETRY_COUNT = 3
EXPORTER_HEALTH_RETRY_TIMEOUT = 3
EXPORTER_DEFAULT_PORT = "10200"
EXPORTER_CRASH_MSG = "Exporter crashed unexpectedly, please refer to systemd logs..."

# Redfish
REDFISH_TIMEOUT = 10
REDFISH_MAX_RETRY = 2


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


TPR_RESOURCES: t.Dict[HWTool, str] = {
    HWTool.STORCLI: "storcli-deb",
    HWTool.PERCCLI: "perccli-deb",
    HWTool.SAS2IRCU: "sas2ircu-bin",
    HWTool.SAS3IRCU: "sas3ircu-bin",
}

EXPORTER_COLLECTOR_MAPPING = {
    HWTool.STORCLI: ["collector.mega_raid"],
    HWTool.PERCCLI: ["collector.poweredge_raid"],
    HWTool.SAS2IRCU: ["collector.lsi_sas_2"],
    HWTool.SAS3IRCU: ["collector.lsi_sas_3"],
    HWTool.SSACLI: ["collector.hpe_ssa"],
    HWTool.IPMI_DCMI: ["collector.ipmi_dcmi"],
    HWTool.IPMI_SEL: ["collector.ipmi_sel"],
    HWTool.IPMI_SENSOR: ["collector.ipmi_sensor"],
    HWTool.REDFISH: ["collector.redfish"],
}

TOOLS_DIR = Path("/usr/sbin")

# SNAP environment
SNAP_COMMON = Path(f"/var/snap/{EXPORTER_NAME}/common")
