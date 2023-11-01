from unittest.mock import patch

import pytest

from os_platform import OSPlatform, UbuntuSeries, get_os_platform


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Java", ""])
@pytest.mark.parametrize("release", ["NT", "Sparkling", "Jaguar", "0.0", ""])
@pytest.mark.parametrize(
    "machine",
    [
        "AMD64",
        "x86_86",
        "arm64",
        "riscv64",
    ],
)
def test_get_os_platform_non_linux(system, release, machine):
    """Get platform from a patched Windows machine."""
    with patch("platform.system", return_value=system):
        with patch("platform.release", return_value=release):
            with patch("platform.machine", return_value=machine):
                result = get_os_platform()
    assert result == OSPlatform(system=system, release=release, machine=machine)


@pytest.mark.parametrize("system", ["ubuntu"])
@pytest.mark.parametrize(
    "release,series",
    [("22.04", UbuntuSeries.JAMMY), ("20.04", UbuntuSeries.FOCAL), ("NR", None)],
)
@pytest.mark.parametrize("machine", ["AMD64", "x86_86", "arm64", "riscv64"])
def test_os_platform_series(system, release, series, machine):
    """Get platform from a patched Windows machine."""
    with patch("platform.system", return_value=system):
        with patch("platform.release", return_value=release):
            with patch("platform.machine", return_value=machine):
                result = get_os_platform()
    assert result == OSPlatform(system=system, release=release, machine=machine)
    assert result.series == series
