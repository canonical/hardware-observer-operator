"""Hardware support config and command helper."""
import json
import logging
import subprocess
import typing as t

from charms.operator_libs_linux.v0 import apt

from config import HWTool

logger = logging.getLogger(__name__)


SUPPORTED_STORAGES = {
    HWTool.SAS2IRCU: [
        # Broadcom
        "SAS2004",
        "SAS2008",
        "SAS2108",
        "SAS2208",
        "SAS2304",
        "SAS2308",
    ],
    HWTool.SAS3IRCU: [
        # Broadcom
        "SAS3004",
        "SAS3008",
    ],
    HWTool.SSACLI: [
        "Smart Array Gen8 Controllers",
        "Smart Array Gen9 Controllers",
    ],
}


def lshw(class_filter: t.Optional[str] = None) -> t.Any:
    """Return lshw output as dict."""
    cmd = "lshw -json"
    if class_filter:
        cmd = cmd + " -c " + class_filter
    try:
        output = subprocess.check_output(cmd.split(), text=True)
        return json.loads(output)
    except subprocess.CalledProcessError as err:
        logger.error(err)
        # Raise error because the cmd should always work.
        raise err


def get_bmc_address() -> t.Optional[str]:
    """Get BMC IP address by ipmitool."""
    apt.add_package("ipmitool", update_cache=False)
    cmd = "ipmitool lan print"
    try:
        output = subprocess.check_output(cmd.split(), text=True)
        for line in output.splitlines():
            values = line.split(":")
            if values[0].strip() == "IP Address":
                return values[1].strip()
    except subprocess.CalledProcessError:
        logger.debug("IPMI is not available")
    return None
