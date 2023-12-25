import unittest
from subprocess import CalledProcessError
from unittest import mock

from charms.operator_libs_linux.v0 import apt

import apt_helpers

APT_CACHE_POLICY_FREEIPMI_TOOLS_OUTPUT = """freeipmi-tools:
  Installed: (none)
  Candidate: 1.6.4-3ubuntu1.1
  Version table:
     1.6.9-2~bpo20.04.1 100
        100 http://tw.archive.ubuntu.com/ubuntu focal-backports/main amd64 Packages
     1.6.4-3ubuntu1.1 500
        500 http://tw.archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
        100 /var/lib/dpkg/status
     1.6.4-3ubuntu1 500
        500 http://tw.archive.ubuntu.com/ubuntu focal/main amd64 Packages
"""


class TestGetCandidateVersion(unittest.TestCase):
    @mock.patch("apt_helpers.check_output")
    def test_install_freeipmi_tools_on_focal(self, mock_check_output):
        mock_check_output.return_value = APT_CACHE_POLICY_FREEIPMI_TOOLS_OUTPUT
        version = apt_helpers.get_candidate_version("freeipmi-tools")
        self.assertEqual(version, "1.6.4-3ubuntu1.1")

    @mock.patch("apt_helpers.check_output")
    def test_checkoutput_failed(self, mock_check_output):
        mock_check_output.side_effect = CalledProcessError(-1, "cmd")

        with self.assertRaises(apt.PackageError):
            apt_helpers.get_candidate_version("freeipmi-tools")

    @mock.patch("apt_helpers.check_output")
    def test_checkoutput_version_not_found_error(self, mock_check_output):
        fake_output = APT_CACHE_POLICY_FREEIPMI_TOOLS_OUTPUT.replace("Candidate", "NotCandidate")
        mock_check_output.return_value = fake_output

        with self.assertRaises(apt.PackageError):
            apt_helpers.get_candidate_version("freeipmi-tools")
