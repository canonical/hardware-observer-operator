from unittest.mock import patch

import pytest

from os_platform import OSPlatform, UbuntuSeries, get_os_platform


@pytest.mark.parametrize("release", ["22.04", "20.04"])
@pytest.mark.parametrize(
    "machine",
    [
        "AMD64",
        "x86_86",
        "arm64",
        "riscv64",
    ],
)
def test_get_os_platform_non_linux(release, machine):
    """Get platform from a patched Windows machine."""
    with patch("distro.info", return_value={"version": release}):
        with patch("platform.machine", return_value=machine):
            result = get_os_platform()
    assert result == OSPlatform(release=release, machine=machine)


@pytest.mark.parametrize(
    "release,series",
    [("22.04", UbuntuSeries.JAMMY), ("20.04", UbuntuSeries.FOCAL), ("NR", None)],
)
@pytest.mark.parametrize("machine", ["AMD64", "x86_86", "arm64", "riscv64"])
def test_os_platform_series(release, series, machine):
    """Get platform from a patched Windows machine."""
    with patch("distro.info", return_value={"version": release}):
        with patch("platform.machine", return_value=machine):
            result = get_os_platform()
    assert result == OSPlatform(release=release, machine=machine)
    assert result.series == series
