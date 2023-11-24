"""Wrapper for `model.Resources`."""

import hashlib
import logging
import os
import typing as t
from pathlib import Path

from checksum import ToolVersionInfo
from config import HWTool
from os_platform import get_os_platform

logger = logging.getLogger(__name__)


class ResourceFileSizeZeroError(Exception):
    """Empty resource error."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"{tool}: {path} has zero size"


class ResourceChecksumError(Exception):
    """Raise if checksum does not match."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"{tool}: {path} has incorrect checksum"


class ResourceNotFoundError(Exception):
    """Raise if resource not found."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"{tool}: {path} does not exists"


class ResourceNotExecutableError(Exception):
    """Raise if resources is not an executable."""

    def __init__(self, tool: HWTool, path: Path):
        """Init."""
        self.message = f"{tool}: {path} is not an executable"


class ResourceIsDirectoryError(Exception):
    """Raise if the resource is a directory."""


def check_file_exists(src: Path) -> bool:
    """Check if file exists or not."""
    if src.is_dir():
        raise ResourceIsDirectoryError(f"{src} is not a file.")
    return src.exists()


def check_file_executable(src: Path) -> bool:
    """Check if file is executable or not."""
    if src.is_dir():
        raise ResourceIsDirectoryError(f"{src} is not a file.")
    return os.access(src, os.X_OK)


def validate_size(path: Path) -> bool:
    """Verify if the file size > 0.

    Because charm focus us to publish the resources on charmhub,
    but most of the hardware related tools have the un-republish
    policy. Currently our solution is publish a empty file which
    size is 0.
    """
    if path.stat().st_size == 0:
        logger.info("%s size is 0, skip install", path)
        return False
    return True


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
