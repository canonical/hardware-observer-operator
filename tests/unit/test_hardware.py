import subprocess
import unittest
from unittest import mock

import pytest

from hardware import _split_at, get_bmc_address, hwinfo, lshw


@pytest.mark.parametrize(
    "s,delimiter,num,expect",
    [("abc-d1-d1-d1-def", "d1", 2, ("abc-d1-", "-d1-def"))],
)
def test_split_at(s, delimiter, num, expect):
    output = _split_at(s, delimiter, num)
    case = unittest.TestCase()
    case.assertCountEqual(output, expect)


class TestHwinfo:
    @pytest.mark.parametrize(
        "hw_classes,expect_cmd,hwinfo_output,expect",
        [
            (
                [],
                ["hwinfo"],
                (
                    ""
                    "============ start debug info ============"
                    "random-string"
                    "random-string"
                    "random-string"
                    "random-string"
                    "=========== end debug info ============"
                    "10: key-a\n"
                    "  [Created at pci.386]\n"
                    "  Unique ID: unique-id-a\n"
                    "  Parent ID: parent-id-a\n"
                    "\n"
                    "11: key-b\n"
                    "  [Created at pci.386]\n"
                    "  Unique ID: unique-id-b\n"
                    "  Parent ID: parent-id-b\n"
                ),
                {
                    "10: key-a": (
                        "10: key-a\n"
                        "  [Created at pci.386]\n"
                        "  Unique ID: unique-id-a\n"
                        "  Parent ID: parent-id-a"
                    ),
                    "11: key-b": (
                        "11: key-b\n"
                        "  [Created at pci.386]\n"
                        "  Unique ID: unique-id-b\n"
                        "  Parent ID: parent-id-b\n"
                    ),
                },
            ),
            (
                ["storage"],
                ["hwinfo", "--storage"],
                (
                    ""
                    "10: key-a\n"
                    "  [Created at pci.386]\n"
                    "  Unique ID: unique-id-a\n"
                    "  Parent ID: parent-id-a\n"
                    "\n"
                    "11: key-b\n"
                    "  [Created at pci.386]\n"
                    "  Unique ID: unique-id-b\n"
                    "  Parent ID: parent-id-b\n"
                ),
                {
                    "10: key-a": (
                        "10: key-a\n"
                        "  [Created at pci.386]\n"
                        "  Unique ID: unique-id-a\n"
                        "  Parent ID: parent-id-a"
                    ),
                    "11: key-b": (
                        "11: key-b\n"
                        "  [Created at pci.386]\n"
                        "  Unique ID: unique-id-b\n"
                        "  Parent ID: parent-id-b\n"
                    ),
                },
            ),
        ],
    )
    @mock.patch("hardware.apt")
    @mock.patch("hardware.subprocess.check_output")
    def test_hwinfo_output(
        self, mock_subprocess, mock_apt, hw_classes, expect_cmd, hwinfo_output, expect
    ):
        mock_subprocess.return_value = hwinfo_output
        output = hwinfo(*hw_classes)
        mock_subprocess.assert_called_with(expect_cmd, text=True)
        assert output == expect


class TestLshw(unittest.TestCase):
    @mock.patch("hardware.apt")
    @mock.patch("hardware.subprocess.check_output")
    def test_lshw_list_output(self, mock_subprocess, mock_apt):
        mock_subprocess.return_value = """[{"expected_output": 1}]"""
        for class_filter in [None, "storage"]:
            output = lshw(class_filter)
            if class_filter is not None:
                mock_subprocess.assert_called_with(
                    f"lshw -json -c {class_filter}".split(),
                    text=True,
                )
                self.assertEqual(output, [{"expected_output": 1}])
            else:
                mock_subprocess.assert_called_with(
                    "lshw -json".split(),
                    text=True,
                )
                self.assertEqual(output, {"expected_output": 1})

    @mock.patch("hardware.subprocess.check_output")
    def test_lshw_dict_output(self, mock_subprocess):
        mock_subprocess.return_value = """{"expected_output": 1}"""
        output = lshw()
        mock_subprocess.assert_called_with(
            "lshw -json".split(),
            text=True,
        )
        self.assertEqual(output, {"expected_output": 1})

    @mock.patch(
        "hardware.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
        return_value="[{}]",
    )
    def test_lshw_error_handling(self, mock_subprocess):
        with self.assertRaises(subprocess.CalledProcessError):
            lshw()


class TestGetBMCAddress(unittest.TestCase):
    @mock.patch("hardware.apt")
    @mock.patch("hardware.subprocess.check_output")
    def test_get_bmc_address(self, mock_check_output, mock_apt):
        mock_check_output.return_value = """
            Set in Progress         : Set Complete
            Auth Type Support       : NONE MD5 PASSWORD
            Auth Type Enable        : Callback : MD5 PASSWORD
                                    : User     : MD5 PASSWORD
                                    : Operator : MD5 PASSWORD
                                    : Admin    : MD5 PASSWORD
                                    : OEM      :
            IP Address Source		: Static Address
            IP Address              : 10.244.120.100
            Subnet Mask             : 255.255.252.0
            MAC Address             : 5a:ba:3c:3b:b4:59
            SNMP Community String   :
            BMC ARP Control         : ARP Responses Enabled, Gratuitous ARP Disabled
            Default Gateway IP      : 10.240.128.1
            802.1q VLAN ID          : Disabled
            802.1q VLAN Priority    : 0
            RMCP+ Cipher Suites     : 0,1,2,3
            Cipher Suite Priv Max   : XXXaXXXXXXXXXXX
                                    :     X=Cipher Suite Unused
                                    :     c=CALLBACK
                                    :     u=USER
                                    :     o=OPERATOR
                                    :     a=ADMIN
                                    :     O=OEM
            Bad Password Threshold  : Not Available
            """.strip()

        output = get_bmc_address()
        self.assertEqual(output, "10.244.120.100")

    @mock.patch("hardware.apt")
    @mock.patch(
        "hardware.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    def test_get_bmc_address_error_handling(self, mock_subprocess, mock_apt):
        output = get_bmc_address()
        self.assertEqual(output, None)
