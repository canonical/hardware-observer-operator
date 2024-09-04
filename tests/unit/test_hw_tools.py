import stat
import subprocess
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock

import ops
import ops.testing
import pytest
import requests
from charms.operator_libs_linux.v0 import apt
from ops.model import ModelError
from parameterized import parameterized

from charm import HardwareObserverCharm
from checksum import (
    PERCCLI_VERSION_INFOS,
    SAS2IRCU_VERSION_INFOS,
    SAS3IRCU_VERSION_INFOS,
    STORCLI_VERSION_INFOS,
)
from config import SNAP_COMMON, TOOLS_DIR, TPR_RESOURCES, HWTool, StorageVendor, SystemVendor
from hw_tools import (
    APTStrategyABC,
    HWToolHelper,
    IPMIDCMIStrategy,
    IPMISELStrategy,
    IPMISENSORStrategy,
    PercCLIStrategy,
    ResourceChecksumError,
    ResourceFileSizeZeroError,
    ResourceInstallationError,
    SAS2IRCUStrategy,
    SAS3IRCUStrategy,
    SmartCtlExporterStrategy,
    SmartCtlStrategy,
    SSACLIStrategy,
    StorCLIStrategy,
    StrategyABC,
    TPRStrategyABC,
    _raid_hw_verifier_hwinfo,
    _raid_hw_verifier_lshw,
    bmc_hw_verifier,
    check_deb_pkg_installed,
    copy_to_snap_common_bin,
    detect_available_tools,
    disk_hw_verifier,
    file_is_empty,
    install_deb,
    make_executable,
    nvidia_gpu_verifier,
    raid_hw_verifier,
    redfish_available,
    remove_deb,
    symlink,
)
from keys import HP_KEYS


def get_mock_path(size: int):
    mock_path = mock.Mock()
    mock_path_stat = mock.Mock()
    mock_path.stat.return_value = mock_path_stat
    mock_path_stat.st_size = size
    return mock_path


@mock.patch("hw_tools.shutil")
@mock.patch("hw_tools.Path")
def test_copy_to_snap_common_bin(mock_path, mock_shutil):
    mock_path_obj = mock.MagicMock()
    mock_path.return_value = mock_path_obj

    copy_to_snap_common_bin(Path("/tmp"), "abc.py")

    mock_path.assert_called_with(f"{SNAP_COMMON}/bin")

    mock_path_obj.mkdir.assert_called()


@mock.patch("hw_tools.apt")
def test_check_deb_pkg_installed_okay(mock_apt):
    mock_pkg = "ipmitool"
    result = check_deb_pkg_installed(mock_pkg)
    assert result is True


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
        self.harness = ops.testing.Harness(HardwareObserverCharm)
        self.addCleanup(self.harness.cleanup)

        self.hw_tool_helper = HWToolHelper()

    def test_01_strategies(self):
        """Check strategies define correctly."""
        strategies = self.hw_tool_helper.strategies
        for strategy in strategies:
            assert isinstance(strategy, (StrategyABC, TPRStrategyABC, APTStrategyABC))

    def test_02_fetch_tools(self):
        """Check each hw_tools_tool has been fetched."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {"resource-a": "path-a", "resource-b": "path-b"}

        for hw_tools_tool in TPR_RESOURCES.values():
            mock_resources._paths[hw_tools_tool] = f"path-{hw_tools_tool}"

        self.hw_tool_helper.fetch_tools(
            resources=mock_resources,
            hw_available={tool for tool in HWTool},
        )

        for tool in TPR_RESOURCES.values():
            mock_resources.fetch.assert_any_call(tool)

    def test_03_fetch_tools_error_handling(self):
        """The fetch fail error should be handled."""
        mock_resources = unittest.mock.MagicMock()
        mock_resources._paths = {}
        mock_resources.fetch.side_effect = ModelError()

        fetch_tools = self.hw_tool_helper.fetch_tools(
            mock_resources,
            hw_available={tool for tool in HWTool},
        )

        for tool in TPR_RESOURCES.values():
            mock_resources.fetch.assert_any_call(tool)

        self.assertEqual(fetch_tools, {})

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.MagicMock(spec=TPRStrategyABC),
            mock.MagicMock(spec=APTStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_04_install(self, mock_strategies):
        """Check strategy is been called."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_available = set()
        for strategy in mock_strategies.return_value:
            mock_hw_available.add(strategy.name)

        self.hw_tool_helper.install(mock_resources, mock_hw_available)

        for strategy in mock_strategies.return_value:
            if isinstance(strategy, TPRStrategyABC):
                path = self.harness.charm.model.resources.fetch(TPR_RESOURCES.get(strategy.name))
                strategy.install.assert_called_with(path)
            elif isinstance(strategy, APTStrategyABC):
                strategy.install.assert_any_call()

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_05_remove(self, mock_strategies):
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_strategies.return_value[0].name = HWTool.STORCLI
        mock_hw_available = {HWTool.STORCLI}
        self.hw_tool_helper.remove(mock_resources, mock_hw_available)
        for strategy in mock_strategies.return_value:
            strategy.remove.assert_called()

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.MagicMock(spec=TPRStrategyABC),
            mock.MagicMock(spec=APTStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_06_install_not_available(self, mock_strategies):
        """Check strategy is been called."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_available = set()

        self.hw_tool_helper.install(mock_resources, mock_hw_available)

        for strategy in mock_strategies.return_value:
            strategy.install.assert_not_called()

    @mock.patch("hw_tools.TPR_RESOURCES", {})
    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[mock.MagicMock(spec=TPRStrategyABC)],
        new_callable=mock.PropertyMock,
    )
    def test_07_install_no_resource(self, mock_strategies):
        """Check tpr strategy is not been called if resource is not defined."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources

        mock_strategies.return_value[0].name = HWTool.STORCLI

        mock_hw_available = set()
        for strategy in mock_strategies.return_value:
            mock_hw_available.add(strategy.name)

        self.hw_tool_helper.install(mock_resources, mock_hw_available)

        for strategy in mock_strategies.return_value:
            strategy.install.assert_not_called()

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_08_remove_not_available(self, mock_strategies):
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_strategies.return_value[0].name = HWTool.STORCLI
        mock_hw_available = set()
        self.hw_tool_helper.remove(mock_resources, mock_hw_available)
        for strategy in mock_strategies.return_value:
            strategy.remove.assert_not_called()

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_09_install_required_resource_not_uploaded(self, _):
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_hw_available = [HWTool.STORCLI, HWTool.PERCCLI]
        ok, msg = self.hw_tool_helper.install(mock_resources, mock_hw_available)
        self.assertFalse(ok)
        self.assertTrue("storcli-deb" in msg)
        self.assertTrue("perccli-deb" in msg)
        self.assertFalse(self.harness.charm._stored.resource_installed)

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
            mock.PropertyMock(spec=APTStrategyABC),
            mock.PropertyMock(spec=APTStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_10_install_strategy_errors(self, mock_strategies):
        """Catch excepted error when execute strategies' install method."""
        self.harness.add_resource("storcli-deb", "storcli.deb")
        self.harness.begin()
        mock_resources = self.harness.charm.model.resources
        mock_strategies.return_value[0].name = HWTool.STORCLI
        mock_strategies.return_value[1].name = HWTool.IPMI_SENSOR
        mock_strategies.return_value[2].name = HWTool.REDFISH

        mock_strategies.return_value[0].install.side_effect = ResourceFileSizeZeroError(
            HWTool.STORCLI, "fake-path"
        )
        mock_strategies.return_value[1].install.side_effect = OSError("Fake os error")
        mock_strategies.return_value[2].install.side_effect = apt.PackageError(
            "Fake apt package error"
        )
        mock_hw_available = [
            HWTool.STORCLI,
            HWTool.IPMI_SENSOR,
            HWTool.REDFISH,
        ]

        ok, msg = self.hw_tool_helper.install(mock_resources, mock_hw_available)

        self.assertFalse(ok)
        self.assertEqual(
            f"Fail strategies: {[HWTool.STORCLI, HWTool.IPMI_SENSOR, HWTool.REDFISH]}",
            msg,
        )

    @mock.patch("hw_tools.file_is_empty", return_value=True)
    def test_11_check_missing_resources_zero_size_resources(self, file_is_empty):
        self.harness.begin()
        ok, msg = self.hw_tool_helper.check_missing_resources(
            hw_available={HWTool.STORCLI},
            fetch_tools={HWTool.STORCLI: "fake-path"},
        )
        self.assertFalse(ok)
        self.assertEqual("Missing resources: ['storcli-deb']", msg)

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_12_check_installed_okay(self, mock_strategies):
        self.harness.begin()
        mock_strategies.return_value[0].name = HWTool.STORCLI
        mock_hw_available = [HWTool.STORCLI]
        self.hw_tool_helper.check_installed(mock_hw_available)
        for strategy in mock_strategies.return_value:
            strategy.check.assert_called()

    @mock.patch(
        "hw_tools.HWToolHelper.strategies",
        return_value=[
            mock.PropertyMock(spec=TPRStrategyABC),
        ],
        new_callable=mock.PropertyMock,
    )
    def test_13_check_installed_okay(self, mock_strategies):
        self.harness.begin()
        mock_strategies.return_value[0].name = HWTool.SSACLI
        mock_hw_available = [HWTool.STORCLI]
        success, msg = self.hw_tool_helper.check_installed(mock_hw_available)
        self.assertTrue(success)
        self.assertEqual(msg, "")

    @mock.patch("hw_tools.os")
    @mock.patch("hw_tools.Path")
    def test_14_check_installed_not_okay(self, mock_os, mock_path):
        self.harness.begin()
        mock_hw_available = [
            HWTool.STORCLI,
            HWTool.PERCCLI,
            HWTool.SAS2IRCU,
            HWTool.SAS3IRCU,
            HWTool.SSACLI,
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
            HWTool.REDFISH,
        ]
        success, msg = self.hw_tool_helper.check_installed(mock_hw_available)
        self.assertFalse(success)


class TestStorCLIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        strategy = StorCLIStrategy()
        strategy.install(path="path-a")
        mock_install_deb.assert_called_with("storcli", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/storcli/storcli64"),
            dst=TOOLS_DIR / "storcli",
        )

    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_empty_resource(self, mock_install_deb, mock_symlink, mock_validate_checksum):
        strategy = StorCLIStrategy()

        with pytest.raises(ResourceFileSizeZeroError):
            strategy.install(get_mock_path(0))
        mock_validate_checksum.assert_not_called()
        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()

    @mock.patch("hw_tools.validate_checksum", return_value=False)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_checksum_fail(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        mock_path = mock.Mock()
        strategy = StorCLIStrategy()
        with pytest.raises(ResourceChecksumError):
            strategy.install(mock_path)
        mock_validate_checksum.assert_called_with(STORCLI_VERSION_INFOS, mock_path)
        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()

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


class TestTPRStrategyABC(unittest.TestCase):
    def test_file_size_is_non_zero(self):
        self.assertFalse(file_is_empty(get_mock_path(size=100)))

    def test_file_size_is_zero(self):
        self.assertTrue(file_is_empty(get_mock_path(size=0)))


class TestSAS2IRCUStrategy(unittest.TestCase):
    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install(
        self, mock_make_executable, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        strategy = SAS2IRCUStrategy()
        strategy.install(path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas2ircu")

    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install_empty_resource(
        self, mock_make_executable, mock_symlink, mock_validate_checksum
    ):
        strategy = SAS2IRCUStrategy()
        with pytest.raises(ResourceFileSizeZeroError):
            strategy.install(get_mock_path(0))

        mock_validate_checksum.assert_not_called()
        mock_make_executable.assert_not_called()
        mock_symlink.assert_not_called()

    @mock.patch("hw_tools.validate_checksum", return_value=False)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_checksum_fail(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        mock_path = mock.Mock()
        strategy = SAS2IRCUStrategy()
        with pytest.raises(ResourceChecksumError):
            strategy.install(mock_path)
        mock_validate_checksum.assert_called_with(SAS2IRCU_VERSION_INFOS, mock_path)
        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()

    def test_remove(self):
        strategy = SAS2IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestSAS3IRCUStrategy(unittest.TestCase):
    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install(
        self, mock_make_executable, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        strategy = SAS3IRCUStrategy()
        strategy.install(path="path-a")
        mock_make_executable.assert_called_with("path-a")
        mock_symlink.assert_called_with(src="path-a", dst=TOOLS_DIR / "sas3ircu")

    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.make_executable")
    def test_install_empty_resource(
        self, mock_make_executable, mock_symlink, mock_validate_checksum
    ):
        strategy = SAS3IRCUStrategy()
        with pytest.raises(ResourceFileSizeZeroError):
            strategy.install(get_mock_path(0))

        mock_validate_checksum.assert_not_called()
        mock_make_executable.assert_not_called()
        mock_symlink.assert_not_called()

    @mock.patch("hw_tools.validate_checksum", return_value=False)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_checksum_fail(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        mock_path = mock.Mock()
        strategy = SAS3IRCUStrategy()
        with pytest.raises(ResourceChecksumError):
            strategy.install(mock_path)
        mock_validate_checksum.assert_called_with(SAS3IRCU_VERSION_INFOS, mock_path)
        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()

    def test_remove(self):
        strategy = SAS3IRCUStrategy()
        with mock.patch.object(strategy, "symlink_bin") as mock_symlink_bin:
            strategy.remove()
            mock_symlink_bin.unlink.assert_called_with(missing_ok=True)


class TestPercCLIStrategy(unittest.TestCase):
    @mock.patch("hw_tools.validate_checksum", return_value=True)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        strategy = PercCLIStrategy()
        strategy.install(path="path-a")
        mock_install_deb.assert_called_with("perccli", "path-a")
        mock_symlink.assert_called_with(
            src=Path("/opt/MegaRAID/perccli/perccli64"),
            dst=TOOLS_DIR / "perccli",
        )

    @mock.patch("hw_tools.validate_checksum")
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_empty_resource(self, mock_install_deb, mock_symlink, mock_check_sum):
        mock_path = mock.Mock()
        mock_path_stat = mock.Mock()
        mock_path.stat.return_value = mock_path_stat
        mock_path_stat.st_size = 0

        strategy = PercCLIStrategy()
        with pytest.raises(ResourceFileSizeZeroError):
            strategy.install(mock_path)

        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()
        mock_check_sum.assert_not_called()

    @mock.patch("hw_tools.validate_checksum", return_value=False)
    @mock.patch("hw_tools.file_is_empty", return_value=False)
    @mock.patch("hw_tools.symlink")
    @mock.patch("hw_tools.install_deb")
    def test_install_checksum_fail(
        self, mock_install_deb, mock_symlink, mock_file_is_empty, mock_validate_checksum
    ):
        mock_path = mock.Mock()
        strategy = PercCLIStrategy()
        with pytest.raises(ResourceChecksumError):
            strategy.install(mock_path)
        mock_validate_checksum.assert_called_with(PERCCLI_VERSION_INFOS, mock_path)
        mock_install_deb.assert_not_called()
        mock_symlink.assert_not_called()

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

        mock_apt.add_package.assert_called_with("ssacli", update_cache=True)

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = SSACLIStrategy()
        mock_repos = mock.Mock()
        mock_apt.RepositoryMapping.return_value = mock_repos

        strategy.remove()
        mock_apt.remove_package.assert_not_called()
        mock_repos.disable.assert_not_called()


class TestIPMISENSORStrategy(unittest.TestCase):
    @mock.patch("apt_helpers.get_candidate_version")
    @mock.patch("apt_helpers.apt")
    def test_install(self, mock_apt, mock_candidate_version):
        strategy = IPMISENSORStrategy()
        mock_candidate_version.return_value = "some-candidate-version"
        strategy.install()

        mock_apt.add_package.assert_called_with(
            "freeipmi-tools", version="some-candidate-version", update_cache=False
        )

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = IPMISENSORStrategy()
        strategy.remove()

        mock_apt.remove_package.assert_not_called()


class TestIPMISELStrategy(unittest.TestCase):
    @mock.patch("apt_helpers.get_candidate_version")
    @mock.patch("apt_helpers.apt")
    def test_install(self, mock_apt, mock_candidate_version):
        strategy = IPMISELStrategy()
        mock_candidate_version.return_value = "some-candidate-version"
        strategy.install()

        mock_apt.add_package.assert_any_call(
            "freeipmi-tools", version="some-candidate-version", update_cache=False
        )
        mock_apt.add_package.assert_any_call(
            "freeipmi-ipmiseld", version="some-candidate-version", update_cache=False
        )

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = IPMISELStrategy()
        strategy.remove()

        mock_apt.remove_package.assert_not_called()


class TestIPMIDCMIStrategy(unittest.TestCase):
    @mock.patch("apt_helpers.get_candidate_version")
    @mock.patch("apt_helpers.apt")
    def test_install(self, mock_apt, mock_candidate_version):
        strategy = IPMIDCMIStrategy()
        mock_candidate_version.return_value = "some-candidate-version"
        strategy.install()

        mock_apt.add_package.assert_called_with(
            "freeipmi-tools", version="some-candidate-version", update_cache=False
        )

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = IPMIDCMIStrategy()
        strategy.remove()

        mock_apt.remove_package.assert_not_called()


class TestSmartCtlStrategy(unittest.TestCase):
    @mock.patch("apt_helpers.get_candidate_version")
    @mock.patch("apt_helpers.apt")
    def test_install(self, mock_apt, mock_candidate_version):
        strategy = SmartCtlStrategy()
        mock_candidate_version.return_value = "some-candidate-version"
        strategy.install()

        mock_apt.add_package.assert_called_with(
            "smartmontools", version="some-candidate-version", update_cache=False
        )

    @mock.patch("hw_tools.apt")
    def test_remove(self, mock_apt):
        strategy = SmartCtlStrategy()
        strategy.remove()

        mock_apt.remove_package.assert_not_called()

    @mock.patch("hw_tools.check_deb_pkg_installed")
    def test_check(self, mock_check_deb_method):
        strategy = SmartCtlStrategy()
        strategy.check()

        mock_check_deb_method.assert_called_with("smartmontools")


class TestSmartCtlExporterStrategy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @mock.patch("hw_tools.requests.get")
    @mock.patch("hw_tools.tarfile.open")
    @mock.patch("hw_tools.make_executable")
    def test_install_success(
        self,
        mock_make_executable,
        mock_tar_open,
        mock_requests_get,
    ):
        strategy = SmartCtlExporterStrategy()
        strategy._resource_dir = self.tmp_path
        strategy._exporter_path = self.tmp_path / "smartctl_exporter"

        mock_response = mock.MagicMock(status_code=HTTPStatus.OK)
        mock_response.content = b"dummy content"
        mock_requests_get.return_value = mock_response
        mock_member = mock.MagicMock(name="member")
        mock_member.name = "smartctl_exporter"
        mock_member_file = mock.MagicMock()
        mock_member_file.read.return_value = b"dummy content"
        mock_tar_open.return_value.__enter__.return_value.getmembers.return_value = [mock_member]
        mock_tar_open.return_value.__enter__.return_value.extractfile.return_value = (
            mock_member_file  # noqa: E501
        )

        strategy.install()

        mock_requests_get.assert_called_with(strategy._release, timeout=60)
        # mock_tar_open.assert_called_with(fileobj=BytesIO(b"dummy content"), mode="r:gz")
        mock_make_executable.assert_called_with(strategy._exporter_path)
        self.assertTrue(strategy._resource_dir.exists())

    @mock.patch("hw_tools.requests.get")
    def test_install_download_failure(self, mock_requests_get):
        strategy = SmartCtlExporterStrategy()
        strategy._resource_dir = self.tmp_path
        strategy._exporter_path = self.tmp_path / "smartctl_exporter"

        mock_response = mock.MagicMock(status_code=HTTPStatus.NOT_FOUND)
        mock_requests_get.return_value = mock_response

        with self.assertRaises(ResourceInstallationError):
            strategy.install()

    @mock.patch("hw_tools.requests.get")
    @mock.patch("hw_tools.tarfile.open")
    def test_install_parse_failure(self, mock_tar_open, mock_requests_get):
        strategy = SmartCtlExporterStrategy()
        strategy._resource_dir = self.tmp_path
        strategy._exporter_path = self.tmp_path / "smartctl_exporter"

        mock_response = mock.MagicMock(status_code=HTTPStatus.OK)
        mock_response.content = b"dummy content"
        mock_requests_get.return_value = mock_response
        mock_member = mock.MagicMock(name="member")
        mock_member.name = "random name"
        mock_member_file = mock.MagicMock()
        mock_member_file.read.return_value = b"dummy content"
        mock_tar_open.return_value.__enter__.return_value.getmembers.return_value = [mock_member]
        mock_tar_open.return_value.__enter__.return_value.extractfile.return_value = (
            mock_member_file  # noqa: E501
        )

        with self.assertRaises(ResourceInstallationError):
            strategy.install()

    @mock.patch("hw_tools.shutil.rmtree")
    def test_remove(self, mock_shutil_rmtree):
        strategy = SmartCtlExporterStrategy()

        strategy.remove()

        mock_shutil_rmtree.assert_called_with(strategy._resource_dir)

    def test_check(self):
        strategy = SmartCtlExporterStrategy()
        strategy._exporter_path = mock.MagicMock()
        strategy._exporter_path.is_file.return_value = True

        result = strategy.check()
        self.assertTrue(result)

        strategy._exporter_path.is_file.assert_called()


@mock.patch("hw_tools.disk_hw_verifier", return_value={7, 8, 9})
@mock.patch("hw_tools.bmc_hw_verifier", return_value={1, 2, 3})
@mock.patch("hw_tools.raid_hw_verifier", return_value={4, 5, 6})
@mock.patch("hw_tools.nvidia_gpu_verifier", return_value={10, 11, 12})
def test_detect_available_tools(
    mock_raid_verifier, mock_bmc_hw_verifier, mock_disk_hw_verifier, mock_nvidia_gpu_verifier
):
    output = detect_available_tools()
    mock_raid_verifier.assert_called()
    mock_bmc_hw_verifier.assert_called()
    mock_disk_hw_verifier.assert_called()
    mock_nvidia_gpu_verifier.assert_called()
    assert output == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}


@mock.patch("hw_tools._raid_hw_verifier_hwinfo", return_value={4, 5, 6})
@mock.patch("hw_tools._raid_hw_verifier_lshw", return_value={1, 2, 3, 4})
def test_raid_hw_verifier(mock_hw_verifier_lshw, mock_hw_verifier_hwinfo):
    output = raid_hw_verifier()
    assert output == {4, 5, 6, 1, 2, 3, 4}


@pytest.mark.parametrize(
    "lshw_output, lshw_storage_output, expect",
    [
        (
            {},
            [{"id": "sas", "product": "XXX SAS3004 XXX", "vendor": StorageVendor.BROADCOM}],
            [HWTool.SAS3IRCU],
        ),
        (
            {},
            [
                {"id": "sas", "product": "XXX SAS2004 XXX", "vendor": StorageVendor.BROADCOM},
                {"id": "sas", "product": "XXX SAS3004 XXX", "vendor": StorageVendor.BROADCOM},
            ],
            [HWTool.SAS2IRCU, HWTool.SAS3IRCU],
        ),
        (
            {},
            [
                {"id": "sas", "product": "XXX SAS2004 XXX", "vendor": StorageVendor.BROADCOM},
            ],
            [HWTool.SAS2IRCU],
        ),
        (
            {"vendor": SystemVendor.HP},
            [
                {"id": "raid", "product": "Smart Array Gen8 Controllers"},
            ],
            [HWTool.SSACLI],
        ),
        (
            {"vendor": SystemVendor.DELL},
            [
                {"id": "raid"},
            ],
            [HWTool.PERCCLI],
        ),
        (
            {},
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
            {"vendor": SystemVendor.DELL},
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
def test_raid_hw_verifier_lshw(mock_lshw, lshw_output, lshw_storage_output, expect):
    mock_lshw.side_effect = [lshw_output, lshw_storage_output]
    output = _raid_hw_verifier_lshw()
    case = unittest.TestCase()
    case.assertCountEqual(output, expect)


@pytest.mark.parametrize(
    "hwinfo_output, expect",
    [
        ({}, []),
        (
            {
                "random-key-a": """
                  [Created at pci.386]
                  Hardware Class: storage
                  Vendor: pci 0x9005 "Adaptec"
                  Device: pci 0x028f "Smart Storage PQI 12G SAS/PCIe 3"
                  SubDevice: pci 0x1100 "Smart Array P816i-a SR Gen10"
                """
            },
            [HWTool.SSACLI],
        ),
        (
            {
                "random-key-a": """
                  [Created at pci.386]
                  Hardware Class: not-valid-class
                  Vendor: pci 0x9005 "Adaptec"
                  Device: pci 0x028f "Smart Storage PQI 12G SAS/PCIe 3"
                  SubDevice: pci 0x1100 "Smart Array P816i-a SR Gen10"
                """
            },
            [],
        ),
    ],
)
@mock.patch("hw_tools.hwinfo")
def test_raid_hw_verifier_hwinfo(mock_hwinfo, hwinfo_output, expect):
    mock_hwinfo.return_value = hwinfo_output
    output = _raid_hw_verifier_hwinfo()
    case = unittest.TestCase()
    case.assertCountEqual(output, expect)


class TestDiskHWVerifier(unittest.TestCase):
    @mock.patch("hw_tools.lshw", return_value=[True])
    def test_disk_available(self, mock_lshw):
        tools = disk_hw_verifier()
        self.assertEqual(tools, {HWTool.SMARTCTL})

    @mock.patch("hw_tools.lshw", return_value=[])
    def test_disk_not_available(self, mock_lshw):
        tools = disk_hw_verifier()
        self.assertEqual(tools, set())


@pytest.mark.parametrize(
    "lshw_output, expect",
    [
        ([], set()),
        (
            [
                {
                    "id": "display",
                    "class": "display",
                    "handle": "PCI:0000:00:02.0",
                    "description": "VGA compatible controller",
                    "product": "TigerLake-H GT1 [UHD Graphics]",
                    "vendor": "Intel Corporation",
                },
            ],
            set(),
        ),
        (
            [
                {
                    "id": "display",
                    "class": "display",
                    "handle": "PCI:0000:01:00.0",
                    "description": "VGA compatible controller",
                    "product": "GA107M [GeForce RTX 3050 Mobile]",
                    "vendor": "NVIDIA Corporation",
                },
                {
                    "id": "display",
                    "class": "display",
                    "handle": "PCI:0000:00:02.0",
                    "description": "VGA compatible controller",
                    "product": "TigerLake-H GT1 [UHD Graphics]",
                    "vendor": "Intel Corporation",
                },
            ],
            {HWTool.DCGM},
        ),
        (
            [
                {
                    "id": "display",
                    "class": "display",
                    "handle": "PCI:0000:01:00.0",
                    "description": "VGA compatible controller",
                    "product": "GA107M [GeForce RTX 3050 Mobile]",
                    "vendor": "NVIDIA Corporation",
                },
                {
                    "id": "display",
                    "class": "display",
                    "handle": "PCI:0000:00:02.0",
                    "description": "3D controller",
                    "product": "H100 [H100 SXM5 80GB]",
                    "vendor": "NVIDIA Corporation",
                },
            ],
            {HWTool.DCGM},
        ),
    ],
)
@mock.patch("hw_tools.lshw")
def test_nvidia_gpu_verifier(mock_lshw, lshw_output, expect):
    mock_lshw.return_value = lshw_output
    assert nvidia_gpu_verifier() == expect


class TestIPMIHWVerifier(unittest.TestCase):
    @mock.patch("hw_tools.requests.get")
    @mock.patch("hw_tools.get_bmc_address", return_value="1.2.3.4")
    def test_redfish_available(self, mock_bmc_address, mock_requests_get):
        mock_response = mock.Mock()
        mock_response.json.return_value = {"some_key": "some_value"}
        mock_requests_get.return_value = mock_response

        result = redfish_available()
        self.assertEqual(result, True)
        mock_bmc_address.assert_called()

    @parameterized.expand(
        [
            (requests.exceptions.HTTPError),
            (requests.exceptions.Timeout),
            (Exception),
        ]
    )
    @mock.patch("hw_tools.requests.get")
    @mock.patch("hw_tools.get_bmc_address", return_value="1.2.3.4")
    def test_redfish_not_available(self, test_except_class, mock_bmc_address, mock_requests_get):
        mock_response = mock.Mock()
        mock_response.raise_for_status.side_effect = test_except_class()
        mock_requests_get.return_value = mock_response

        result = redfish_available()
        self.assertEqual(result, False)
        mock_bmc_address.assert_called_once()

    @mock.patch("hw_tools.requests.get")
    @mock.patch("hw_tools.get_bmc_address", return_value="1.2.3.4")
    def test_redfish_not_available_bad_response(self, mock_bmc_address, mock_requests_get):
        mock_response = mock.Mock()
        mock_response.json.return_value = {}
        mock_requests_get.return_value = mock_response

        result = redfish_available()
        self.assertEqual(result, False)
        mock_bmc_address.assert_called_once()

    @mock.patch("hw_tools.redfish_available", return_value=True)
    @mock.patch("hw_tools.subprocess")
    @mock.patch("hw_tools.apt_helpers")
    def test_bmc_hw_verifier(self, mock_apt_helpers, mock_subprocess, mock_redfish_available):
        output = bmc_hw_verifier()
        mock_apt_helpers.add_pkg_with_candidate_version.assert_called_with("freeipmi-tools")
        self.assertCountEqual(
            output, [HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH]
        )

    @mock.patch("hw_tools.redfish_available", return_value=False)
    @mock.patch(
        "hw_tools.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(-1, "cmd"),
    )
    @mock.patch("hw_tools.apt_helpers")
    def test_bmc_hw_verifier_error_handling(
        self, mock_apt_helpers, mock_check_output, mock_redfish_available
    ):
        output = bmc_hw_verifier()
        mock_apt_helpers.add_pkg_with_candidate_version.assert_called_with("freeipmi-tools")
        self.assertEqual(output, set())

    @mock.patch("hw_tools.redfish_available", return_value=False)
    @mock.patch("hw_tools.apt_helpers")
    def test_bmc_hw_verifier_mixed(self, mock_apt_helpers, mock_redfish_available):
        """Test a mixture of failures and successes for ipmi."""

        def mock_get_response_ipmi(ipmi_call):
            if ipmi_call == "ipmimonitoring --sdr-cache-recreate".split():
                pass
            elif ipmi_call == "ipmi-sel --sdr-cache-recreate".split():
                pass
            elif ipmi_call == "ipmi-dcmi --get-system-power-statistics".split():
                raise subprocess.CalledProcessError(-1, "cmd")

        with mock.patch("hw_tools.subprocess.check_output", side_effect=mock_get_response_ipmi):
            output = bmc_hw_verifier()
            mock_apt_helpers.add_pkg_with_candidate_version.assert_called_with("freeipmi-tools")
            self.assertCountEqual(output, [HWTool.IPMI_SENSOR, HWTool.IPMI_SEL])
