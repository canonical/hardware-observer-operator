"""Config."""
from pathlib import Path

# EXPORTER_NAME = "prometheus-hardware-exporter"
EXPORTER_NAME = "cocona"


# Register every vendoer's tool here.
VENDOR_TOOLS = [
    "storecli-deb",
]

# SNAP envionment

SNAP_COMMON = Path(f"/var/snap/{EXPORTER_NAME}/common")
