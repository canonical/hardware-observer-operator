import subprocess
import unittest
from unittest import mock

from hardware import get_bmc_address, lshw


class TestLshw(unittest.TestCase):
    @mock.patch("hardware.subprocess.check_output")
    def test_lshw(self, mock_subprocess):
        mock_subprocess.return_value = "[{}]"
        for class_filter in [None, "storage"]:
            lshw(class_filter)
            if class_filter is not None:
                mock_subprocess.assert_called_with(
                    f"lshw -json -c {class_filter}".split(),
                    text=True,
                )
            else:
                mock_subprocess.assert_called_with(
                    "lshw -json".split(),
                    text=True,
                )

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
