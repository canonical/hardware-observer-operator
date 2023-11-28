"""Hardware support config and command helper."""
import json
import logging
import subprocess
import typing as t

from charms.operator_libs_linux.v0 import apt
from redfish import redfish_client
from redfish.rest.v1 import InvalidCredentialsError

from config import REDFISH_MAX_RETRY, REDFISH_TIMEOUT, HWTool, StorageVendor, SystemVendor

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


def install_apt_package(pkg_name: str) -> None:
    """Install APT package if it's not installed."""
    try:
        apt.DebianPackage.from_installed_package(pkg_name)
    except apt.PackageNotFoundError:
        logger.info("installing %s", pkg_name)
        apt.add_package(pkg_name, update_cache=False)
    else:
        logger.info("%s already installed", pkg_name)


def get_bmc_address() -> t.Optional[str]:
    """Get BMC IP address by ipmitool."""
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


def validate_redfish_credential(ip_address: str, username: str = "", password: str = "") -> bool:
    """Validate redfish credential by logging in with the credential."""
    try:
        result = True
        redfish_obj = redfish_client(
            base_url=f"https://{ip_address}",
            username=username,
            password=password,
            timeout=REDFISH_TIMEOUT,
            max_retry=REDFISH_MAX_RETRY,
        )
        redfish_obj.login()
    except InvalidCredentialsError:
        result = False
        logger.error("invalid redfish credential")
    except Exception as err:  # pylint: disable=W0718
        result = False
        logger.error("redfish not available")
        logger.error("cannot connect to redfish: %s", str(err))
    else:
        redfish_obj.logout()

    return result


def raid_hw_verifier() -> t.List[HWTool]:
    """Verify if the HWTool support RAID card exists on machine."""
    hw_info = lshw()
    system_vendor = hw_info.get("vendor")
    storage_info = lshw(class_filter="storage")

    tools = set()

    for info in storage_info:
        _id = info.get("id")
        product = info.get("product")
        vendor = info.get("vendor")
        driver = info.get("configuration", {}).get("driver")
        if _id == "sas":
            # sas3ircu
            if (
                any(
                    _product
                    for _product in SUPPORTED_STORAGES[HWTool.SAS3IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS3IRCU)
            # sas2ircu
            if (
                any(
                    _product
                    for _product in SUPPORTED_STORAGES[HWTool.SAS2IRCU]
                    if _product in product
                )
                and vendor == StorageVendor.BROADCOM
            ):
                tools.add(HWTool.SAS2IRCU)

        if _id == "raid":
            # ssacli
            if system_vendor == SystemVendor.HP and any(
                _product for _product in SUPPORTED_STORAGES[HWTool.SSACLI] if _product in product
            ):
                tools.add(HWTool.SSACLI)
            # perccli
            elif system_vendor == SystemVendor.DELL:
                tools.add(HWTool.PERCCLI)
            # storcli
            elif driver == "megaraid_sas" and vendor == StorageVendor.BROADCOM:
                tools.add(HWTool.STORCLI)
    return list(tools)


def bmc_hw_verifier() -> t.List[HWTool]:
    """Verify if the ipmi is available on the machine.

    Using ipmitool to verify, the package will be removed in removing stage.
    """
    bmc_address = get_bmc_address()
    if not bmc_address:
        logger.info("BMC is not available.")
        return []

    tools = []
    if bmc_address is not None:
        tools.append(HWTool.IPMI)
    if validate_redfish_credential(bmc_address):
        tools.append(HWTool.REDFISH)

    return tools


def get_hw_tool_white_list() -> t.List[HWTool]:
    """Return HWTool white list."""
    # bmc_hw_verifier requires `ipmitool`
    install_apt_package("ipmitool")
    bmc_white_list = bmc_hw_verifier()
    raid_white_list = raid_hw_verifier()
    return raid_white_list + bmc_white_list
