# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Literals for the charm."""
import pydantic

from hardware import get_cuda_version_from_driver


# TODO: Add more charm configuration options. See #468
class HWObserverConfig(pydantic.BaseModel):
    class Config:
        """Pydantic config."""

        allow_population_by_field_name = True

    dcgm_snap_channel: str = pydantic.Field(
        default="", description="Snap channel for DCGM", alias="dcgm-snap-channel"
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

        cls.check_cuda_compatibility_with_dcgm(track)

        return value

    @staticmethod
    def check_cuda_compatibility_with_dcgm(track: str) -> None:
        """Check if the NVIDIA driver is compatible with the selected DCGM track.

        v3 is compatible with cuda versions 10, 11 and 12.
        v4 is compatible with cuda versions 11, 12 and 13.
        See https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html for
        more details.
        """
        cuda_version = get_cuda_version_from_driver()

        if cuda_version == 13 and track == "v3":
            raise ValueError("DCGM v3 is not compatible with NVIDIA driver version 580 or higher.")
        if cuda_version == 10 and track == "v4":
            raise ValueError("DCGM v4 requires NVIDIA driver version 450 or higher.")
