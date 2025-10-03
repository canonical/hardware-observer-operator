# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from literals import HWObserverConfig


@pytest.fixture(autouse=True)
def mock_driver_to_cuda():
    with patch("literals.get_cuda_version_from_driver") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_driver_version():
    with patch("literals.get_nvidia_driver_version") as mock:
        yield mock


@pytest.mark.parametrize("dcgm_config", ["auto"])
def test_accepts_auto(dcgm_config):
    """Test that 'auto' passes validation without errors."""
    cfg = HWObserverConfig(dcgm_snap_channel=dcgm_config)
    assert cfg.dcgm_snap_channel == dcgm_config


@pytest.mark.parametrize(
    "dcgm_config", ["v3/stable", "v3/edge", "v3/candidate", "v4/stable", "v4/edge", "v4/candidate"]
)
def test_valid_channels(mock_driver_to_cuda, dcgm_config):
    """Test valid v3 and v4 channels for supported CUDA versions."""
    mock_driver_to_cuda.return_value = 12

    cfg = HWObserverConfig(dcgm_snap_channel=dcgm_config)
    assert cfg.dcgm_snap_channel == dcgm_config


@pytest.mark.parametrize("dcgm_config", ["invalid/stable", "foo/edge", "123/candidate"])
def test_invalid_track(mock_driver_to_cuda, dcgm_config):
    """Invalid tracks should raise ValueError."""
    mock_driver_to_cuda.return_value = 12
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(dcgm_snap_channel=dcgm_config)
    assert "Invalid track" in str(e.value)


@pytest.mark.parametrize("dcgm_config", ["v3/unknown", "v4/beta", "v3/dev"])
def test_invalid_risk(mock_driver_to_cuda, dcgm_config):
    """Invalid risk should raise ValueError."""
    mock_driver_to_cuda.return_value = 12
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(dcgm_snap_channel=dcgm_config)
    assert "Invalid channel risk" in str(e.value)


def test_missing_risk(mock_driver_to_cuda):
    """Values without the risk should raise ValueError."""
    mock_driver_to_cuda.return_value = 12
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(dcgm_snap_channel="v3")
    assert "Channel must be in the form" in str(e.value)


def test_incompatible_v3_with_cuda13(mock_driver_to_cuda):
    """v3 should fail if CUDA version is 13 (driver 580+)."""
    mock_driver_to_cuda.return_value = 13
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(dcgm_snap_channel="v3/stable")
    assert "not compatible" in str(e.value)


def test_incompatible_v4_with_cuda10(mock_driver_to_cuda):
    """v4 should fail if CUDA version is 10 (old driver)."""
    mock_driver_to_cuda.return_value = 10
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(dcgm_snap_channel="v4/stable")
    assert "not compatible" in str(e.value)
