"""Hardware support config and command helper."""

import json
import logging
import re
import subprocess
import typing as t
from pathlib import Path

from charms.operator_libs_linux.v0 import apt

from config import HWTool

logger = logging.getLogger(__name__)

# File path that contains the NVIDIA driver that is loaded and its version
NVIDIA_DRIVER_PATH = Path("/proc/driver/nvidia/version")


LSHW_SUPPORTED_STORAGES = {
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

HWINFO_SUPPORTED_STORAGES = {
    HWTool.SSACLI: [
        [
            "Hardware Class: storage",
            'Vendor: pci 0x9005 "Adaptec"',
            'Device: pci 0x028f "Smart Storage PQI 12G SAS/PCIe 3"',
            'SubDevice: pci 0x1100 "Smart Array P816i-a SR Gen10"',
        ]
    ]
}


def lshw(class_filter: t.Optional[str] = None) -> t.Any:
    """Return lshw output as dict."""
    cmd = "lshw -json"
    if class_filter:
        cmd = cmd + " -c " + class_filter
    try:
        output = subprocess.check_output(cmd.split(), text=True)
        json_output = json.loads(output)
        # lshw has different output on different ubuntu series
        # if class_filter is not provided.
        if not class_filter and isinstance(json_output, list):
            json_output = json_output[0]
        return json_output
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


def hwinfo(*args: str) -> t.Dict[str, str]:
    """Run hwinfo command and return output as dictionary.

    Args:
        args: Probe for a particular hardware class.
    Returns:
        hw_info: hardware information dictionary
    """
    apt.add_package("hwinfo", update_cache=False)
    hw_classes = list(args)
    for idx, hw_item in enumerate(args):
        hw_classes[idx] = "--" + hw_item
    hw_info_cmd = ["hwinfo"] + hw_classes

    output = subprocess.check_output(hw_info_cmd, text=True)
    if "start debug info" in output.splitlines()[0]:
        output = output.split("=========== end debug info ============")[1]

    hardware: t.Dict[str, str] = {}
    for item in output.split("\n\n"):
        key = item.splitlines()[0].strip()
        hardware[key] = item
    return hardware


def is_nvidia_driver_loaded() -> bool:
    """Determine if an NVIDIA driver has been loaded."""
    return NVIDIA_DRIVER_PATH.exists()


def get_nvidia_driver_version() -> int:
    """Get the NVIDIA driver version installed on the system."""
    try:
        nvidia_driver_version = NVIDIA_DRIVER_PATH.read_text()
        match = re.search(r"NVRM version:.*?(\d+\.\d+(?:\.\d+)*)", nvidia_driver_version)
        if match:
            return int(match.group(1).split(".")[0])
    except FileNotFoundError:
        logger.error("NVIDIA driver version file not found.")
        raise


def get_cuda_version_from_driver() -> int:
    """Map the installed NVIDIA driver version to CUDA version."""
    driver_version = get_nvidia_driver_version()

    if driver_version >= 580:
        return 13
    elif driver_version >= 525:
        return 12
    elif driver_version >= 450:
        logger.warning(
            "The installed NVIDIA driver version '%s' might not be supported in next DCGM "
            "releases. Consider updating the NVIDIA driver.",
            driver_version,
        )
        return 11
    else:
        logger.warning(
            "The installed NVIDIA driver version '%s' is quite old and might not be supported "
            "by recent DCGM versions. Consider updating the NVIDIA driver.",
            driver_version,
        )
        return 10
