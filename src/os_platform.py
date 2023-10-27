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

    JAMMY = "22.04"
    FOCAL = "20.04"
    BIONIC = "18.04"
    XENIAL = "16.04"


@dataclasses.dataclass
class OSPlatform:
    """Description of an operating system platform."""

    system: str
    release: str
    machine: str

    @property
    def series(self) -> t.Optional[UbuntuSeries]:
        """Return series base on system and release."""
        if self.system == "ubuntu":
            for series in UbuntuSeries:
                if series == self.release:
                    return series
        return None


def get_os_platform() -> OSPlatform:
    """Determine a system/release combo for an OS using /etc/os-release if available."""
    system = platform.system()
    release = platform.release()
    machine = platform.machine()

    if system == "Linux":
        info = distro.info()
        system = info.get("id", system)
        # Treat Ubuntu derivatives as Ubuntu, as they should be compatible.
        if system != "ubuntu" and "ubuntu" in info.get("like", "").split():
            system = "ubuntu"
        release = info.get("version", release)

    return OSPlatform(system=system, release=release, machine=machine)
