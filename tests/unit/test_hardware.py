import subprocess
import unittest
from unittest import mock

from hardware import lshw


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
