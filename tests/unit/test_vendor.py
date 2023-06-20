import stat
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import ops
import ops.testing
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError

from charm import PrometheusHardwareExporterCharm
from config import SNAP_COMMON, TOOLS_DIR, TPR_VENDOR_TOOLS, VENDOR_TOOLS
from keys import HP_KEYS
from vendor import (
    APTStrategyABC,
    PercCLIStrategy,
    SAS2IRCUStrategy,
    SAS3IRCUStrategy,
    SSACLIStrategy,
    StorCLIStrategy,
    TPRStrategyABC,
    VendorHelper,
    copy_to_snap_common_bin,
    install_deb,
    make_executable,
    remove_deb,
    symlink,
)


@mock.patch("vendor.shutil")
@mock.patch("vendor.Path")
def test_copy_to_snap_common_bin(mock_path, mock_shutil):
    mock_path_obj = mock.MagicMock()
    mock_path.return_value = mock_path_obj

    copy_to_snap_common_bin(Path("/tmp"), "abc.py")

    mock_path.assert_called_with(f"{SNAP_COMMON}/bin")

    mock_path_obj.mkdir.assert_called()


class TestSymlink(unittest.TestCase):
    def test_symlink(self):
        mock_src = mock.Mock()
        mock_dst = mock.Mock()
        symlink(src=mock_src, dst=mock_dst)
        mock_dst.unlink.assert_called_with(missing_ok=True)
        mock_dst.symlink_to.assert_called_with(mock_src)

    def test_symlink_error_handling(self):
        mock_src = mock.Mock()
        mock_dst = mock.Mock()
        mock_dst.symlink_to.side_effect = OSError()

        with self.assertRaises(OSError):
            symlink(src=mock_src, dst=mock_dst)

        mock_dst.unlink.assert_called_with(missing_ok=True)
        mock_dst.symlink_to.assert_called_with(mock_src)


class TestMakeExecutable(unittest.TestCase):
    @mock.patch("vendor.os")
    def test_make_executable(self, mock_os):
        mock_src = mock.Mock()
        make_executable(mock_src)
        mock_os.chmod.assert_called_with(mock_src, stat.S_IEXEC)
        mock_os.chown.assert_called_with(mock_src, 0, 0)

    @mock.patch("vendor.os")
    def test_make_executable_error_handling(self, mock_os):
        mock_os.chown.side_effect = OSError()
        mock_src = mock.Mock()
        with self.assertRaises(OSError):
            make_executable(mock_src)
        mock_os.chmod.assert_called_with(mock_src, stat.S_IEXEC)
        mock_os.chown.assert_called_with(mock_src, 0, 0)


class TestVendorHelper(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(PrometheusHardwareExporterCharm)
        self.addCleanup(self.harness.cleanup)

        self.vendor_helper = VendorHelper()

    def test_01_strategies(self):
        """Check strategies define correctly."""
        strategies = self.vendor_helper.strategies
        self.assertEqual(
            strategies.keys(),
            {
                "storcli-deb",
                "perccli-deb",
                "sas2ircu-bin",
                "sas3ircu-bin",
                "ssacli",
            },
        )
        for _, v in strategies.items():
            assert isinstance(v, (TPRStrategyABC, APTStrategyABC))

        # Special cases
        assert isinstance(strategies.get("storcli-deb"), StorCLIStrategy)

    def test_02_fetch_tools(self):
        """Check each vendor_tool has been fetched."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {"resource-a": "path-a", "resource-b": "path-b"}

        for vendor_tool in VENDOR_TOOLS:
            mock_resources._paths[vendor_tool] = f"path-{vendor_tool}"

        fetch_tools = self.vendor_helper.fetch_tools(mock_resources)
        for tool in TPR_VENDOR_TOOLS:
            mock_resources.fetch.assert_any_call(tool)

        self.assertEqual(["ssacli"] + list(fetch_tools.keys()), VENDOR_TOOLS)

    def test_03_fetch_tools_error_handling(self):
        """The fetch fail error should be handled."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {}
        mock_resources.fetch.side_effect = ModelError()

        fetch_tools = self.vendor_helper.fetch_tools(mock_resources)

        for tool in TPR_VENDOR_TOOLS:
            mock_resources.fetch.assert_any_call(tool)

        self.assertEqual(fetch_tools, {})

    @mock.patch(
        "vendor.VendorHelper.strategies",
        return_value={
            "storcli-deb": mock.MagicMock(spec=TPRStrategyABC),
            "ssacli": mock.MagicMock(spec=APTStrategyABC),
        },
        new_callable=mock.PropertyMock,
    )
    def test_04_install(self, mock_strategies):
        """Check strategy is been called."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        self.vendor_helper.install(mock_resources)

        for name, value in mock_strategies.return_value.items():
            if isinstance(value, TPRStrategyABC):
                path = self.harness.charm.model.resources.fetch(name)
                value.install.assert_any_call(name, path)
            elif isinstance(value, APTStrategyABC):
                value.install.assert_any_call()

    @mock.patch(
        "vendor.VendorHelper.strategies",
        return_value={},
        new_callable=mock.PropertyMock,
    )
    @mock.patch("vendor.logger")
    def test_05_install_not_strategies(self, mock_logger, mock_strategies):
        """logger.warning is triggered if strategy has not been defined."""
        self.harness.add_resource(
            "storcli-deb",
            "storcli.deb",
        )
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        self.vendor_helper.install(mock_resources)
        mock_logger.warning.assert_any_call(
            "Could not find install strategy for tool %s", "storcli-deb"
        )

    @mock.patch(
        "vendor.VendorHelper.strategies",
        return_value={
            "storcli-deb": mock.MagicMock(spec=TPRStrategyABC),
        },
        new_callable=mock.PropertyMock,
    )
    def test_06_remove(self, mock_strategies):
        self.harness.add_resource(
            "storcli-deb",
            "storcli.deb",
        )
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_resources.fetch("storcli-deb")
        self.vendor_helper.remove(mock_resources)
        for name, value in mock_strategies.return_value.items():
            value.remove.assert_called()

    @mock.patch(
        "vendor.VendorHelper.strategies",
        return_value={},
        new_callable=mock.PropertyMock,
    )
    @mock.patch("vendor.logger")
    def test_07_remove_not_strategies(self, mock_logger, mock_strategies):
        """logger.warning is triggered if strategy has not been defined."""
        self.harness.add_resource(
            "storcli-deb",
            "storcli.deb",
        )
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        self.vendor_helper.remove(mock_resources)
        mock_logger.warning.assert_any_call(
            "Could not find remove strategy for tool %s", "storcli-deb"
        )


class TestStorCLIInstrallStrategy(unittest.TestCase):
    @mock.patch("vendor.symlink")
    @mock.patch("vendor.install_deb")
    def test_install(self, mock_install_deb, mock_symlink):
        strategy = StorCLIStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_install_deb.assert_called_with("name-a", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/storcli/storcli64"),
            dst=TOOLS_DIR / "storcli",
        )

    @mock.patch("vendor.symlink")
    @mock.patch("vendor.remove_deb")
    def test_remove(self, mock_remove_deb, mock_symlink):
        strategy = StorCLIStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)
            mock_remove_deb.assert_called_with(pkg=strategy.name)


class TestDeb(unittest.TestCase):
    @mock.patch("vendor.subprocess")
    def test_install_deb(self, mock_subprocess):
        install_deb(name="name-a", path="path-a")
        mock_subprocess.check_output.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )

    @mock.patch(
        "vendor.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    def test_install_deb_error_handling(self, mock_subprocess_check_outpout):
        """Check the error handling of install."""
        with self.assertRaises(apt.PackageError):
            install_deb(name="name-a", path="path-a")
        mock_subprocess_check_outpout.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )

    @mock.patch("vendor.subprocess")
    def test_remove_deb(self, mock_subprocess):
        remove_deb(pkg="pkg-a")
        mock_subprocess.check_output.assert_called_with(
            ["dpkg", "--remove", "pkg-a"], universal_newlines=True
        )

    @mock.patch(
        "vendor.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    def test_remove_deb_error_handling(self, mock_subprocess_check_outpout):
        """Check the error handling of install."""
        with self.assertRaises(apt.PackageError):
            remove_deb(pkg="pkg-a")

        mock_subprocess_check_outpout.assert_called_with(
            ["dpkg", "--remove", "pkg-a"], universal_newlines=True
        )


class TestSAS2IRCUStrategy(unittest.TestCase):
    @mock.patch("vendor.symlink")
    @mock.patch("vendor.make_executable")
    def test_install(self, mock_make_executable, mock_symlink):
        strategy = SAS2IRCUStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas2ircu")

    def test_remove(self):
        strategy = SAS2IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestSAS3IRCUStrategy(unittest.TestCase):
    @mock.patch("vendor.symlink")
    @mock.patch("vendor.make_executable")
    def test_install(self, mock_make_executable, mock_symlink):
        strategy = SAS3IRCUStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas3ircu")

    def test_remove(self):
        strategy = SAS3IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestPercCLIStrategy(unittest.TestCase):
    @mock.patch("vendor.symlink")
    @mock.patch("vendor.install_deb")
    def test_install(self, mock_install_deb, mock_symlink):
        strategy = PercCLIStrategy()
        strategy.install(name="name-a", path="path-a")
        mock_install_deb.assert_called_with("name-a", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/perccli/perccli64"),
            dst=TOOLS_DIR / "perccli",
        )

    @mock.patch("vendor.symlink")
    @mock.patch("vendor.remove_deb")
    def test_remove(self, mock_remove_deb, mock_symlink):
        strategy = PercCLIStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)
            mock_remove_deb.assert_called_with(pkg=strategy.name)


class TestSSACLIStrategy(unittest.TestCase):
    @mock.patch("vendor.apt")
    def test_install(self, mock_apt):
        strategy = SSACLIStrategy()
        mock_repos = mock.Mock()
        mock_apt.RepositoryMapping.return_value = mock_repos

        strategy.install()
        mock_repos.add.assert_called_with(strategy.repo)
        for key in HP_KEYS:
            mock_apt.import_key.assert_any_call(key)

    @mock.patch("vendor.apt")
    def test_remove(self, mock_apt):
        strategy = SSACLIStrategy()
        mock_repos = mock.Mock()
        mock_apt.RepositoryMapping.return_value = mock_repos

        strategy.remove()
        mock_apt.remove_package.assert_called_with(strategy.pkg)
        mock_repos.disable.assert_called_with(strategy.repo)
