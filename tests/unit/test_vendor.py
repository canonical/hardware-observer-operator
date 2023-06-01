import subprocess
import unittest
from pathlib import Path
from unittest import mock

import ops
import ops.testing
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError

from charm import PrometheusHardwareExporterCharm
from config import VENDOR_TOOLS
from vendor import DebInstallStrategy, InstallStrategyABC, StorCLIInstallStrategy, VendorHelper


class TestVendorHelper(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(PrometheusHardwareExporterCharm)
        self.addCleanup(self.harness.cleanup)

        self.vendor_helper = VendorHelper()

    def test_strategies(self):
        """Check strategies define correctly."""
        strategies = self.vendor_helper.strategies
        assert strategies.keys() == {"storecli-deb"}

        for _, v in strategies.items():
            assert isinstance(v, InstallStrategyABC)

        # Special cases
        assert isinstance(strategies.get("storecli-deb"), StorCLIInstallStrategy)

    def test_fetch_tools(self):
        """Check each vendor_tool has been fetched."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {"resource-a": "path-a", "resource-b": "path-b"}

        for vendor_tool in VENDOR_TOOLS:
            mock_resources._paths[vendor_tool] = f"path-{vendor_tool}"

        fetch_tools = self.vendor_helper.fetch_tools(mock_resources)

        for vendor_tool in VENDOR_TOOLS:
            mock_resources.fetch.assert_called_with(vendor_tool)

        self.assertEqual(fetch_tools, VENDOR_TOOLS)

    def test_fetch_tools_error_handling(self):
        """The fetch fail error should be handled."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {}
        mock_resources.fetch.side_effect = ModelError()

        fetch_tools = self.vendor_helper.fetch_tools(mock_resources)

        for vendor_tool in VENDOR_TOOLS:
            mock_resources.fetch.assert_called_with(vendor_tool)

        self.assertEqual(fetch_tools, [])

    @mock.patch(
        "vendor.VendorHelper.strategies",
        return_value={
            "storecli-deb": mock.MagicMock(),
        },
        new_callable=mock.PropertyMock,
    )
    def test_install(self, mock_strategies):
        """Check strategy is been called."""
        self.harness.add_resource("storecli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        self.vendor_helper.install(mock_resources)

        for name, value in mock_strategies.return_value.items():
            path = self.harness.charm.model.resources.fetch(name)
            value.install.assert_called_with(name, path)


class TestStorCLIInstrallStrategy(unittest.TestCase):
    @mock.patch("vendor.copy_to_snap_common_bin")
    @mock.patch("vendor.DebInstallStrategy.install")
    def test_install(self, mock_super_install, mock_copy_to_snap_common_bin):
        strategy = StorCLIInstallStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_super_install.assert_called_with("name-a", "path-a")
        mock_copy_to_snap_common_bin.assert_called_with(
            filename="storcli",
            source=Path("/opt/MegaRAID/storcli/storcli64"),
        )


class TestDebInstallStrategy(unittest.TestCase):
    @mock.patch("vendor.subprocess")
    def test_install(self, mock_subprocess):
        strategy = DebInstallStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_subprocess.check_output.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )

    @mock.patch(
        "vendor.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    def test_install_error_handling(self, mock_subprocess_check_outpout):
        """Check the error handling of install."""
        strategy = DebInstallStrategy()
        with self.assertRaises(apt.PackageError):
            strategy.install(name="name-a", path="path-a")

        mock_subprocess_check_outpout.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )
