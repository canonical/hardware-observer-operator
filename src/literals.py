# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Literals for the charm."""
import logging

import pydantic

from hardware import (
    dcgm_v3_compatible,
    dcgm_v4_compatible,
    get_cuda_version_from_driver,
    get_nvidia_driver_version,
)

logger = logging.getLogger(__name__)


class HWObserverConfig(pydantic.BaseModel):
    class Config:
        """Pydantic config."""

        allow_population_by_field_name = True

    dcgm_snap_channel: str = pydantic.Field(
        default="", description="Snap channel for DCGM", alias="dcgm-snap-channel"
    )
    redfish_disable: bool = pydantic.Field(
        default=True, description="Disable Redfish exporter", alias="redfish-disable"
    )
    ipmi_driver_type: str = pydantic.Field(
        default="", description="Driver type for IPMI", alias="ipmi-driver-type"
    )
    redfish_username: str = pydantic.Field(
        default="", description="Username for Redfish", alias="redfish-username"
    )
    redfish_password: str = pydantic.Field(
        default="", description="Password for Redfish", alias="redfish-password"
    )
    hardware_exporter_port: int = pydantic.Field(
        default=10200, description="Port for hardware exporter", alias="hardware-exporter-port"
    )
    smartctl_exporter_port: int = pydantic.Field(
        default=10201, description="Port for smartctl exporter", alias="smartctl-exporter-port"
    )
    exporter_log_level: str = pydantic.Field(
        default="INFO", description="Log level for exporters", alias="exporter-log-level"
    )
    collect_timeout: int = pydantic.Field(
        default=10, description="Timeout for collectors in seconds", alias="collect-timeout"
    )
    smartctl_exporter_snap_channel: str = pydantic.Field(
        default="latest/stable",
        description="Snap channel for smartctl exporter",
        alias="smartctl-exporter-snap-channel",
    )

    @pydantic.validator("hardware_exporter_port", "smartctl_exporter_port")
    @classmethod
    def validate_port(cls, value):
        """Validate that port is within valid range."""
        if not 1 <= value <= 65535:
            raise ValueError(f"Port must be in range [1, 65535], got {value}")
        return value

    @pydantic.validator("exporter_log_level")
    @classmethod
    def validate_log_level(cls, value):
        """Validate and normalise log level to uppercase."""
        upper = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if upper not in allowed:
            raise ValueError(f"Invalid log level '{value}'. Must be one of: {sorted(allowed)}")
        return upper

    @pydantic.validator("collect_timeout")
    @classmethod
    def validate_collect_timeout(cls, value):
        """Validate that collect timeout is positive."""
        if value <= 0:
            raise ValueError(f"collect-timeout must be > 0, got {value}")
        return value

    @pydantic.validator("dcgm_snap_channel", pre=True)
    @classmethod
    def validate_dcgm_channel(cls, value):
        """Validate the DCGM snap channel format and driver compatibility."""
        if value == "auto":
            return value
        try:
            track, risk = value.split("/", 1)
        except ValueError:
            raise ValueError("Channel must be in the form '<track>/<risk>'")

        valid_tracks = {"v3", "v4"}
        valid_risks = {"stable", "edge", "candidate"}

        if track not in valid_tracks:
            raise ValueError(f"Invalid track '{track}'. Must be one of: {sorted(valid_tracks)}")
        if risk not in valid_risks:
            raise ValueError(
                f"Invalid channel risk '{risk}'. Must be one of: {sorted(valid_risks)}"
            )

        driver_version = get_nvidia_driver_version()
        cuda_version = get_cuda_version_from_driver()
        if not dcgm_v3_compatible(cuda_version, track) and not dcgm_v4_compatible(
            cuda_version, track
        ):
            raise ValueError(f"DCGM {track} is not compatible with driver {driver_version}.")

        return value

    @pydantic.validator("redfish_disable", pre=True)
    @classmethod
    def validate_redfish_disable(cls, value):
        """Validate the Redfish disable option.

        Juju already checks for boolean values, but we want to log a warning.
        """
        if value is True:
            logger.warning(
                "Redfish alert rules are considered experimental and may be changed or removed "
                "in future releases."
            )
        return value

    @pydantic.validator("ipmi_driver_type", pre=True)
    @classmethod
    def validate_ipmi_driver_type(cls, value):
        """Validate the IPMI driver type option."""
        driver = value.upper()
        choices = {"LAN", "LAN_2_0", "KCS", "SSIF", "OPENIPMI", "SUNBMC", ""}
        if driver not in choices:
            raise ValueError(
                f"Invalid IPMI driver type '{value}'. Must be one of: {sorted(choices)}"
            )
        return driver

    @pydantic.root_validator
    @classmethod
    def check_ipmi_redfish_compatibility(cls, values):
        """Ensure IPMI LAN mode is not used together with Redfish enabled.

        Using IPMI over LAN and Redfish simultaneously may conflict; require
        that if `ipmi-driver-type` contains 'LAN', then `redfish-disable`
        must be True.
        """
        ipmi = (values.get("ipmi_driver_type") or "").upper()
        redfish_disabled = values.get("redfish_disable", True)

        if "LAN" in ipmi and redfish_disabled is False:
            raise ValueError("Cannot use use IPMI over LAN and redfish exporter simultaneously.")

        return values
