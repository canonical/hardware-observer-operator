"""Apt helper module for missing features in operator_libs_linux."""
import re
from subprocess import PIPE, CalledProcessError, check_output
from typing import Optional

from charms.operator_libs_linux.v0 import apt


def get_candidate_version(package: str) -> Optional[str]:
    """Get candiate version of package from apt-cache.

    Related issue: https://github.com/canonical/operator-libs-linux/issues/113
    """
    try:
        output = check_output(
            ["apt-cache", "policy", package], stderr=PIPE, universal_newlines=True
        )
    except CalledProcessError as e:
        raise apt.PackageError(f"Could not list packages in apt-cache: {e.output}") from None

    lines = [line.strip() for line in output.strip().split("\n")]
    for line in lines:
        candidate_matcher = re.compile(r"^Candidate:\s(?P<version>(.*))")
        matches = candidate_matcher.search(line)
        if matches:
            return matches.groupdict().get("version")
    raise apt.PackageError(f"Could not find candidate version package in apt-cache: {output}")


def add_pkg_with_candidate_version(pkg: str) -> None:
    """Install package with apt-cache candidate version.

    Related issue: https://github.com/canonical/operator-libs-linux/issues/113
    """
    version = get_candidate_version(pkg)
    apt.add_package(pkg, version=version, update_cache=False)
