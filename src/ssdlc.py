# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""SSDLC (Secure Software Development Lifecycle) Logging.

These events provide critical visibility into the asset's lifecycle and health, and can help
detect potential tampering or malicious activities aimed at altering system behavior.

Logging these events allows for the identification of unauthorized changes to system states,
such as unapproved restarts or unexpected shutdowns, which may indicate security incidents
or availability attacks, or changes to security settings.
"""

from datetime import datetime, timezone
from enum import Enum
from logging import getLogger

logger = getLogger(__name__)


class SSDLCSysEvent(str, Enum):  # noqa: N801
    """Constant event defined in SSDLC."""

    STARTUP = "sys_startup"
    SHUTDOWN = "sys_shutdown"
    RESTART = "sys_restart"
    CRASH = "sys_crash"


_EVENT_MESSAGE_MAPS = {
    SSDLCSysEvent.STARTUP: "hardware observer start service %s",
    SSDLCSysEvent.SHUTDOWN: "hardware observer shutdown service %s",
    SSDLCSysEvent.RESTART: "hardware observer restart service %s",
    SSDLCSysEvent.CRASH: "hardware observer service %s crash",
}


class Service(str, Enum):
    HARDWARE_EXPORTER = "hardware-exporter"
    DCGM_EXPORTER = "dcgm"
    SMARTCTL_EXPORTER = "smartctl-exporter"


# Mapping from exporter_name to Service enum
EXPORTER_NAME_TO_SERVICE = {
    "hardware-exporter": Service.HARDWARE_EXPORTER,
    "dcgm": Service.DCGM_EXPORTER,
    "smartctl-exporter": Service.SMARTCTL_EXPORTER,
}


def log_ssdlc_system_event(event: SSDLCSysEvent, service: str, msg: str = ""):
    """Log system startup event in SSDLC required format.

    Args:
        event: The SSDLC system event type
        service: exporter_name string (e.g., "hardware-exporter", "dcgm")
        msg: Optional additional message
    """
    # Map exporter_name to Service enum
    service_enum = EXPORTER_NAME_TO_SERVICE.get(service)
    if not service_enum:
        logger.warning("Unknown service name: %s, skipping SSDLC logging", service)
        return

    event_msg = _EVENT_MESSAGE_MAPS[event].format(service_enum)

    now = datetime.now(timezone.utc).astimezone()
    logger.warning(
        {
            "datetime": now.isoformat(),
            "appid": f"service.{service_enum.value}",
            "event": f"{event.value}:{service_enum.value}",
            "level": "WARN",
            "description": f"{event_msg} {msg}".strip(),
        },
    )
