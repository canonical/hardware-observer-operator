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


# TODO: Add more charm configuration options. See #468
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
