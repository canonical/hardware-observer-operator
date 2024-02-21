"""Hardware support config and command helper."""

import json
import logging
import subprocess
import typing as t

from charms.operator_libs_linux.v0 import apt

from config import HWTool

logger = logging.getLogger(__name__)


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


def _split_at(s: str, c: str, n: int) -> t.Tuple[str, str]:
    """Split a string 's' at the 'n'th occurrence of delimiter 'c'.

    Parameters:
        s (str): The string to split.
        c (str): Delimiter for splitting.
        n (int): Occurrence of 'c' to split at.

    Returns:
        Tuple[str, str]: The string before and after the 'n'th occurrence of 'c'.
    """
    words = s.split(c)
    return c.join(words[:n]), c.join(words[n:])


def hwinfo(*args: str) -> t.Dict[str, str]:
    """Run hwinfo command and return output as dicturary.

    Args:
        args: Probe for a particular hardware class.
    Returns:
        hw_info: hardware information dicturary
    """
    apt.add_package("hwinfo", update_cache=False)
    hw_classes = list(args)
    for idx, hw_item in enumerate(args):
        hw_classes[idx] = "--" + hw_item
    hw_classes.insert(0, "hwinfo")

    output = subprocess.check_output(hw_classes, text=True)
    if "start debug info" in output.splitlines()[0]:
        output = _split_at(output, "=========== end debug info ============", 1)[1]

    hardwares: t.Dict[str, str] = {}
    for item in output.split("\n\n"):
        key = item.splitlines()[0].strip()
        hardwares[key] = item
    return hardwares
