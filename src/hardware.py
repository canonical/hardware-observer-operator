"""Hardware support config and command helper."""
import json
import logging
import subprocess
import typing as t

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
