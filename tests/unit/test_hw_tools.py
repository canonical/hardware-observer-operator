import stat
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import ops
import ops.testing
import pytest
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError

from charm import PrometheusHardwareExporterCharm
from config import SNAP_COMMON, TOOLS_DIR, TPR_RESOURCES, HWTool, StorageVendor, SystemVendor
from hw_tools import (
    APTStrategyABC,
    HWToolHelper,
    IPMIStrategy,
    PercCLIStrategy,
    SAS2IRCUStrategy,
    SAS3IRCUStrategy,
    SSACLIStrategy,
    StorCLIStrategy,
    TPRStrategyABC,
    copy_to_snap_common_bin,
    get_hw_tool_white_list,
    install_deb,
    ipmi_hw_verifier,
    make_executable,
    raid_hw_verifier,
    remove_deb,
    symlink,
)
from keys import HP_KEYS


@mock.patch("hw_tools.shutil")
@mock.patch("hw_tools.Path")
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
    @mock.patch("hw_tools.os")
    def test_make_executable(self, mock_os):
        mock_src = mock.Mock()
        make_executable(mock_src)
        mock_os.chmod.assert_called_with(mock_src, stat.S_IEXEC)
        mock_os.chown.assert_called_with(mock_src, 0, 0)

    @mock.patch("hw_tools.os")
    def test_make_executable_error_handling(self, mock_os):
        mock_os.chown.side_effect = OSError()
        mock_src = mock.Mock()
        with self.assertRaises(OSError):
            make_executable(mock_src)
        mock_os.chmod.assert_called_with(mock_src, stat.S_IEXEC)
        mock_os.chown.assert_called_with(mock_src, 0, 0)


class TestHWToolHelper(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(PrometheusHardwareExporterCharm)
        self.addCleanup(self.harness.cleanup)

        self.hw_tool_helper = HWToolHelper()

    def test_01_strategies(self):
        """Check strategies define correctly."""
        strategies = self.hw_tool_helper.strategies
        for strategy in strategies:
            assert isinstance(strategy, (TPRStrategyABC, APTStrategyABC))

    def test_02_fetch_tools(self):
        """Check each hw_tools_tool has been fetched."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {"resource-a": "path-a", "resource-b": "path-b"}

        for hw_tools_tool in TPR_RESOURCES.values():
            mock_resources._paths[hw_tools_tool] = f"path-{hw_tools_tool}"

        self.hw_tool_helper.fetch_tools(mock_resources)

        for tool in TPR_RESOURCES.values():
            mock_resources.fetch.assert_any_call(tool)

    def test_03_fetch_tools_error_handling(self):
        """The fetch fail error should be handled."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {}
        mock_resources.fetch.side_effect = ModelError()

        fetch_tools = self.hw_tool_helper.fetch_tools(mock_resources)

        for tool in TPR_RESOURCES.values():
            mock_resources.fetch.assert_any_call(tool)

        self.assertEqual(fetch_tools, {})

    @mock.patch("hw_tools.get_hw_tool_white_list")
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.MagicMock(spec=TPRStrategyABC),
            mock.MagicMock(spec=APTStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_04_install(self, mock_strategies, mock_hw_white_list):
        """Check strategy is been called."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_white_list.return_value = []
        for strategy in mock_strategies.return_value:
            mock_hw_white_list.return_value.append(strategy.name)

        self.hw_tool_helper.install(mock_resources)

        for strategy in mock_strategies.return_value:
            if isinstance(strategy, TPRStrategyABC):
                path = self.harness.charm.model.resources.fetch(TPR_RESOURCES.get(strategy.name))
                strategy.install.assert_called_with(path)
            elif isinstance(strategy, APTStrategyABC):
                strategy.install.assert_any_call()

    @mock.patch("hw_tools.get_hw_tool_white_list", return_value=[HWTool.STORCLI])
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_05_remove(self, mock_strategies, _):
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_strategies.return_value[0].name = HWTool.STORCLI
        self.hw_tool_helper.remove(mock_resources)
        for strategy in mock_strategies.return_value:
            strategy.remove.assert_called()

    @mock.patch("hw_tools.get_hw_tool_white_list")
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.MagicMock(spec=TPRStrategyABC),
            mock.MagicMock(spec=APTStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_06_install_not_in_white_list(self, mock_strategies, mock_hw_white_list):
        """Check strategy is been called."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_white_list.return_value = []

        self.hw_tool_helper.install(mock_resources)

        for strategy in mock_strategies.return_value:
            strategy.install.assert_not_called()

    @mock.patch("hw_tools.TPR_RESOURCES", {})
    @mock.patch("hw_tools.get_hw_tool_white_list")
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[mock.MagicMock(spec=TPRStrategyABC)],
        new_callable=mock.PropertyMock,
    )
    def test_07_install_no_resource(self, mock_strategies, mock_hw_white_list):
        """Check tpr strategy is not been called if resource is not defined."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_white_list.return_value = []
        for strategy in mock_strategies.return_value:
            mock_hw_white_list.return_value.append(strategy.name)

        self.hw_tool_helper.install(mock_resources)

        for strategy in mock_strategies.return_value:
            strategy.install.assert_not_called()

    @mock.patch("hw_tools.get_hw_tool_white_list", return_value=[])
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_05_remove_not_in_white_list(self, mock_strategies, _):
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_strategies.return_value[0].name = HWTool.STORCLI
        self.hw_tool_helper.remove(mock_resources)
        for strategy in mock_strategies.return_value:
            strategy.remove.assert_not_called()


class TestStorCLIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install(self, mock_install_deb, mock_symlink):
        strategy = StorCLIStrategy()
        strategy.install(path="path-a")
        mock_install_deb.assert_called_with("storcli", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/storcli/storcli64"),
            dst=TOOLS_DIR / "storcli",
        )

    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.remove_deb")
    def test_remove(self, mock_remove_deb, mock_symlink):
        strategy = StorCLIStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)
            mock_remove_deb.assert_called_with(pkg=strategy.name)


class TestDeb(unittest.TestCase):
    @mock.patch("hw_tools.subprocess")
    def test_install_deb(self, mock_subprocess):
        install_deb(name="name-a", path="path-a")
        mock_subprocess.check_output.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )

    @mock.patch(
        "hw_tools.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    def test_install_deb_error_handling(self, mock_subprocess_check_outpout):
        """Check the error handling of install."""
        with self.assertRaises(apt.PackageError):
            install_deb(name="name-a", path="path-a")
        mock_subprocess_check_outpout.assert_called_with(
            ["dpkg", "-i", "path-a"], universal_newlines=True
        )

    @mock.patch("hw_tools.subprocess")
    def test_remove_deb(self, mock_subprocess):
        remove_deb(pkg="pkg-a")
        mock_subprocess.check_output.assert_called_with(
            ["dpkg", "--remove", "pkg-a"], universal_newlines=True
        )

    @mock.patch(
        "hw_tools.subprocess.check_output",
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
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install(self, mock_make_executable, mock_symlink):
        strategy = SAS2IRCUStrategy()
        strategy.install(path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas2ircu")

    def test_remove(self):
        strategy = SAS2IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestSAS3IRCUStrategy(unittest.TestCase):
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install(self, mock_make_executable, mock_symlink):
        strategy = SAS3IRCUStrategy()
        strategy.install(path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas3ircu")

    def test_remove(self):
        strategy = SAS3IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestPercCLIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install(self, mock_install_deb, mock_symlink):
        strategy = PercCLIStrategy()
        strategy.install(path="path-a")
        mock_install_deb.assert_called_with("perccli", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/perccli/perccli64"),
            dst=TOOLS_DIR / "perccli",
        )

    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.remove_deb")
    def test_remove(self, mock_remove_deb, mock_symlink):
        strategy = PercCLIStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)
            mock_remove_deb.assert_called_with(pkg=strategy.name)


class TestSSACLIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.apt")
    def test_install(self, mock_apt):
        strategy = SSACLIStrategy()
        mock_repos = mock.Mock()
        mock_apt.RepositoryMapping.return_value = mock_repos

        strategy.install()
        mock_repos.add.assert_called_with(strategy.repo)
        for key in HP_KEYS:
            mock_apt.import_key.assert_any_call(key)

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = SSACLIStrategy()
        mock_repos = mock.Mock()
        mock_apt.RepositoryMapping.return_value = mock_repos

        strategy.remove()
        mock_apt.remove_package.assert_called_with(strategy.pkg)
        mock_repos.disable.assert_called_with(strategy.repo)


class TestIPMIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.apt")
    def test_install(self, mock_apt):
        strategy = IPMIStrategy()
        strategy.install()

        mock_apt.add_package.assert_called_with("freeipmi-tools")

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = IPMIStrategy()
        strategy.remove()

        mock_apt.remove_package.assert_called_with("freeipmi-tools")


@mock.patch("hw_tools.ipmi_hw_verifier")
@mock.patch("hw_tools.raid_hw_verifier")
def test_get_hw_tool_white_list(mock_raid_verifier, mock_ipmi_hw_verifier):
    get_hw_tool_white_list()
    mock_raid_verifier.assert_called()
    mock_ipmi_hw_verifier.assert_called()


@pytest.mark.parametrize(
    "lshw_output, lshw_storage_output, expect",
    [
        (
            [{}],
            [{"id": "sas", "product": "XXX SAS3004 XXX", "vendor": StorageVendor.BROADCOM}],
            [HWTool.SAS3IRCU],
        ),
        (
            [{}],
            [
                {"id": "sas", "product": "XXX SAS2004 XXX", "vendor": StorageVendor.BROADCOM},
                {"id": "sas", "product": "XXX SAS3004 XXX", "vendor": StorageVendor.BROADCOM},
            ],
            [HWTool.SAS2IRCU, HWTool.SAS3IRCU],
        ),
        (
            [{}],
            [
                {"id": "sas", "product": "XXX SAS2004 XXX", "vendor": StorageVendor.BROADCOM},
            ],
            [HWTool.SAS2IRCU],
        ),
        (
            [{"vendor": SystemVendor.HP}],
            [
                {"id": "raid", "product": "Smart Array Gen8 Controllers"},
            ],
            [HWTool.SSACLI],
        ),
        (
            [{"vendor": SystemVendor.DELL}],
            [
                {"id": "raid"},
            ],
            [HWTool.PERCCLI],
        ),
        (
            [{}],
            [
                {
                    "id": "raid",
                    "vendor": StorageVendor.BROADCOM,
                    "configuration": {"driver": "megaraid_sas"},
                },
            ],
            [HWTool.STORCLI],
        ),
        (
            [{"vendor": SystemVendor.DELL}],
            [
                {
                    "id": "raid",
                    "vendor": StorageVendor.BROADCOM,
                    "configuration": {"driver": "megaraid_sas"},
                },
            ],
            [HWTool.PERCCLI],
        ),
    ],
)
@mock.patch("hw_tools.lshw")
def test_raid_hw_verifier(mock_lshw, lshw_output, lshw_storage_output, expect):
    mock_lshw.side_effect = [lshw_output, lshw_storage_output]
    output = raid_hw_verifier()
    case = unittest.TestCase()
    case.assertCountEqual(output, expect)


class TestIPMIHWVerifier(unittest.TestCase):
    @mock.patch("hw_tools.subprocess")
    @mock.patch("hw_tools.apt")
    def test_ipmi_hw_verifier(self, mock_apt, mock_subprocess):
        output = ipmi_hw_verifier()
        mock_apt.add_package.assert_called_with("ipmitool", update_cache=True)
        mock_subprocess.check_output.assert_called_with("ipmitool lan print".split())
        self.assertCountEqual(output, [HWTool.IPMI])

    @mock.patch(
        "hw_tools.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    @mock.patch("hw_tools.apt")
    def test_ipmi_hw_verifier_error_handling(self, mock_apt, mock_check_output):
        output = ipmi_hw_verifier()
        mock_apt.add_package.assert_called_with("ipmitool", update_cache=True)
        mock_check_output.assert_called_with("ipmitool lan print".split())
        self.assertEqual(output, [])
