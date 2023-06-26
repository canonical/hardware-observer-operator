"""Config."""
from pathlib import Path

EXPORTER_NAME = "hardware-exporter"
EXPORTER_CONFIG_PATH = Path(f"/etc/{EXPORTER_NAME}-config.yaml")
EXPORTER_SERVICE_PATH = Path(f"/etc/systemd/system/{EXPORTER_NAME}.service")
EXPORTER_CONFIG_TEMPLATE = f"{EXPORTER_NAME}-config.yaml.j2"
EXPORTER_SERVICE_TEMPLATE = f"{EXPORTER_NAME}.service.j2"


# Register every vendor's tool here.
VENDOR_TOOLS = [
    "storecli-deb",
]
TOOLS_DIR = Path("/usr/sbin")

# SNAP envionment

SNAP_COMMON = Path(f"/var/snap/{EXPORTER_NAME}/common")
