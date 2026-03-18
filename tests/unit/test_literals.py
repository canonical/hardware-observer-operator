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


def test_invalid_ipmi_driver_type():
    """Test that invalid ipmi_driver_type raises a ValidationError."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(ipmi_driver_type="LAN_")
        assert "Invalid ipmi_driver_type" in str(e.value)


def test_mutually_exclusive_ipmi_over_lan_and_redfish_disabled():
    """Test that ipmi_driver_type can be empty when redfish is disabled."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(redfish_disable=False, ipmi_driver_type="LAN_2_0")
        assert "simultaneously" in str(e.value)


@pytest.mark.parametrize("port", [1, 10200, 65535])
def test_valid_hardware_exporter_port(port):
    """Valid ports within [1, 65535] should pass."""
    cfg = HWObserverConfig(hardware_exporter_port=port)
    assert cfg.hardware_exporter_port == port


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_invalid_hardware_exporter_port(port):
    """Ports outside [1, 65535] should raise ValidationError."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(hardware_exporter_port=port)
    assert "Port must be in range" in str(e.value)


@pytest.mark.parametrize("port", [1, 10201, 65535])
def test_valid_smartctl_exporter_port(port):
    """Valid ports within [1, 65535] should pass."""
    cfg = HWObserverConfig(smartctl_exporter_port=port)
    assert cfg.smartctl_exporter_port == port


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_invalid_smartctl_exporter_port(port):
    """Ports outside [1, 65535] should raise ValidationError."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(smartctl_exporter_port=port)
    assert "Port must be in range" in str(e.value)


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_valid_log_levels(level):
    """All standard log levels should pass."""
    cfg = HWObserverConfig(exporter_log_level=level)
    assert cfg.exporter_log_level == level


@pytest.mark.parametrize("level", ["debug", "info", "Warning"])
def test_log_level_normalised_to_upper(level):
    """Log level should be normalised to uppercase."""
    cfg = HWObserverConfig(exporter_log_level=level)
    assert cfg.exporter_log_level == level.upper()


@pytest.mark.parametrize("level", ["TRACE", "VERBOSE", "not-valid"])
def test_invalid_log_level(level):
    """Invalid log levels should raise ValidationError."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(exporter_log_level=level)
    assert "Invalid log level" in str(e.value)


@pytest.mark.parametrize("timeout", [1, 10, 300])
def test_valid_collect_timeout(timeout):
    """Positive timeout values should pass."""
    cfg = HWObserverConfig(collect_timeout=timeout)
    assert cfg.collect_timeout == timeout


@pytest.mark.parametrize("timeout", [0, -1])
def test_invalid_collect_timeout(timeout):
    """Zero or negative timeout should raise ValidationError."""
    with pytest.raises(ValidationError) as e:
        HWObserverConfig(collect_timeout=timeout)
    assert "collect-timeout must be > 0" in str(e.value)
