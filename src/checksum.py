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
"""Checksum definition, check functions and related utils."""
import hashlib
import logging
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from os_platform import Architecture, UbuntuSeries, get_os_platform

logger = logging.getLogger(__name__)


class ResourceChecksumError(Exception):
    """Raise if checksum does not match."""


@dataclass
class ToolVersionInfo:
    """Tool version information for checksum comparison."""

    version: str
    supported_architectures: t.List[Architecture]
    sha256_checksum: str
    link: t.Optional[str] = None
    desc: str = ""
    support_all_series: bool = False
    supported_series: t.List[UbuntuSeries] = field(default_factory=lambda: [])


STORCLI_VERSION_INFOS: t.List[ToolVersionInfo] = [
    ToolVersionInfo(
        version="007.2705.0000.0000",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/1232743397",
        desc="MR 7.27",
        sha256_checksum="45ff0d3c7fc8b77f64de7de7b3698307971546a6be00982934a19ee44f5d91bb",
    ),
    ToolVersionInfo(
        version="007.2612.0000.0000",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/1232743291",
        desc="MR 7.26",
        sha256_checksum="5ab2c1b608934626817828ced85e4aeaee7dc97fbd6e3f4fed00b13a95a06e14",
    ),
    ToolVersionInfo(
        version="007.2508.0000.0000",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/1232743203",
        desc="MR 7.25",
        sha256_checksum="17c3f5292de6491f1388c9305ba65836730614b6defe17039b427fced2f75e0b",
    ),
    ToolVersionInfo(
        version="007.2408.0000.0000",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/1232743081",
        desc="MR 7.24",
        sha256_checksum="8ecf2d46e253e243c5d169adcd84f2701e52e3815913694f074e80af5a98cbab",
    ),
    ToolVersionInfo(
        version="007.2310.0000.0000",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/Unified_storcli_all_os_7.2309.0000.0000.zip",
        desc="MR 7.23",
        sha256_checksum="94cbef2ec2ca58700a49e646a7bded3a49ddab4646a9d5d178bc4ccb2996cb73",
    ),
]

PERCCLI_VERSION_INFOS: t.List[ToolVersionInfo] = [
    ToolVersionInfo(
        version="007.2313.0000.0000",
        supported_series=[UbuntuSeries.JAMMY, UbuntuSeries.FOCAL],
        supported_architectures=[Architecture.X86_64],
        link="https://www.dell.com/support/home/zh-tw/drivers/driversdetails?driverid=tdghn",
        desc="A14",
        sha256_checksum="043f7d6235cf125072e95d748cb98f5db42965f218de30f6f72f5503a626e4e3",
    ),
    ToolVersionInfo(
        version="007.1623.0000.0000",
        supported_series=[UbuntuSeries.FOCAL, UbuntuSeries.BIONIC, UbuntuSeries.XENIAL],
        supported_architectures=[Architecture.X86_64],
        link="https://www.dell.com/support/home/zh-tw/drivers/driversdetails?driverid=j91yg",
        desc="A11",
        sha256_checksum="e46d955241c932023caf63862cd9dacb2b723b7f944340efb0e5afb6a2681e9d",
    ),
    ToolVersionInfo(
        version="007.1420.0000.0000",
        supported_series=[
            UbuntuSeries.FOCAL,
            UbuntuSeries.BIONIC,
            UbuntuSeries.XENIAL,
        ],
        supported_architectures=[Architecture.X86_64],
        link="https://www.dell.com/support/home/zh-tw/drivers/driversdetails?driverid=n65f1",
        desc="A10",
        sha256_checksum="8a405000ea592e1d2999313ade07609a7abcfa24d1b9b35bb242bb6aff75a6be",
    ),
    ToolVersionInfo(
        version="007.1327.0000.0000",
        supported_series=[UbuntuSeries.FOCAL, UbuntuSeries.BIONIC, UbuntuSeries.XENIAL],
        supported_architectures=[Architecture.X86_64],
        link="https://www.dell.com/support/home/zh-tw/drivers/driversdetails?driverid=d6ywp",
        desc="A09",
        sha256_checksum="53c8ee43808779f8263c25b3cb975d816d207659684f3c7de1df4bbd2447ead4",
    ),
]

SAS2IRCU_VERSION_INFOS: t.List[ToolVersionInfo] = [
    ToolVersionInfo(
        version="20.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/12351735",
        desc="P20, linux_x86",
        sha256_checksum="37467826d0b22aad47287efe70bb34e47f475d70e9b1b64cbd63f57607701e73",
    ),
    ToolVersionInfo(
        version="19.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/12351734",
        desc="P19, linux_x86",
        sha256_checksum="4baaec21865973c0a6da617e37850cc27512715e6ab22df18b1f67d068e5095c",
    ),
    ToolVersionInfo(
        version="18.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/12351733",
        desc="P18, linux_x86",
        sha256_checksum="b6ed72275066e80ebe9813cd15f1d019eba9daddbd9dfd8ad426da78801f15d8",
    ),
    ToolVersionInfo(
        version="17.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/12351732",
        desc="P17, linux_x86",
        sha256_checksum="07e9236b99bbe4a3ae6148f8668e1ce0331d83c2fcb0c4841d000454c6200c1f",
    ),
    ToolVersionInfo(
        version="16.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/12351731",
        desc="P16, linux_x86",
        sha256_checksum="a8653117067847042bb83e7b51f02d8f2db94e91ce95842efea0dffcb655c966",
    ),
]

SAS3IRCU_VERSION_INFOS: t.List[ToolVersionInfo] = [
    ToolVersionInfo(
        version="17.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P16.zip",
        desc="P16, linux_x86",
        sha256_checksum="7fa299a36254c582cf579d197463d6e59ffa9270b7241d98d0e477f05235be26",
    ),
    ToolVersionInfo(
        version="16.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P15.zip",
        desc="P15, linux_x86",
        sha256_checksum="f150eb37bb332668949a3eccf9636e0e03f874aecd17a39d586082c6be1386bd",
    ),
    ToolVersionInfo(
        version="15.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P14.zip",
        desc="P14, linux_x86",
        sha256_checksum="5825b90964d1950551e5ed5100ddf1141360b0acf8dd3c6ddb4fe5874d6bbabb",
    ),
    ToolVersionInfo(
        version="14.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P13.zip",
        desc="P13, linux_x86",
        sha256_checksum="1ce45e57efa0a2d8c5c3d61a0950ab7e950a317aff3155fc1831099e19274c32",
    ),
    ToolVersionInfo(
        version="13.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P12.zip",
        desc="P12, linux_x86",
        sha256_checksum="cb4010a3d2bc4f9b75859a0c599d889f9fb847e4dfc88abf74082a13b9490a59",
    ),
    ToolVersionInfo(
        version="12.00.00.00",
        support_all_series=True,
        supported_architectures=[Architecture.X86_64],
        link="https://docs.broadcom.com/docs/SAS3IRCU_P11.zip",
        desc="P11, linux_x86",
        sha256_checksum="458d51b030468901fc8a207088070e6ce82db34b181d9190c8f849605f1b9b6d",
    ),
]


def validate_checksum(support_version_infos: t.List[ToolVersionInfo], path: Path) -> bool:
    """Validate checksum of resource file by checking with supported versions.

    Returns True if resource is supported by the charm, architecture, and
    checksum validation is successful.
    """
    os_platform = get_os_platform()

    supported_checksums = []
    for info in support_version_infos:
        if os_platform.machine in info.supported_architectures and (
            info.support_all_series or os_platform.series in info.supported_series
        ):
            supported_checksums.append(info.sha256_checksum)

    with open(path, "rb") as f:
        sha256_hash = hashlib.sha256(f.read()).hexdigest()

    if sha256_hash in supported_checksums:
        return True
    logger.warning("Checksum validation fail, path: %s hash: %s", path, sha256_hash)
    return False
