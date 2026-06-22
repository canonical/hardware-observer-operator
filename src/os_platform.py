# Copyright 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft
"""Platform-related Charmcraft utilities."""

import dataclasses
import platform
import typing as t
from enum import Enum

import distro


class UbuntuSeries(str, Enum):
    """Ubuntu Series."""

    NOBLE = "24.04"
    JAMMY = "22.04"
    FOCAL = "20.04"
    BIONIC = "18.04"
    XENIAL = "16.04"


class Architecture(str, Enum):
    """Host architecture."""

    X86_64 = "x86_64"
    AARCH64 = "aarch64"


@dataclasses.dataclass
class OSPlatform:
    """Description of an operating system platform."""

    release: str
    machine: str

    @property
    def series(self) -> t.Optional[UbuntuSeries]:
        """Return series base on system and release."""
        for series in UbuntuSeries:
            if series == self.release:
                return series
        return None

    @property
    def architecture(self) -> t.Optional[Architecture]:
        """Return architecture base on machine type."""
        for arch in Architecture:
            if arch == self.machine:
                return arch
        return None


def get_os_platform() -> OSPlatform:
    """Determine a system/release combo for an OS using /etc/os-release if available."""
    machine = platform.machine()
    info = distro.info()
    release = info.get("version", "")

    return OSPlatform(release=release, machine=machine)
