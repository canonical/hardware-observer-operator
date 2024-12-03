import stat
import subprocess
import unittest
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
    DCGMExporterStrategy,
    HWToolHelper,
    IPMIDCMIStrategy,
    IPMISELStrategy,
    IPMISENSORStrategy,
    NVIDIADriverStrategy,
    PercCLIStrategy,
    ResourceChecksumError,
    ResourceFileSizeZeroError,
    ResourceInstallationError,
    SAS2IRCUStrategy,
    SAS3IRCUStrategy,
    SnapStrategy,
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
    remove_legacy_smartctl_exporter,
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
        self.harness.begin()
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
        mock_strategies.return_value[0].name = HWTool.SSACLI
        mock_hw_available = [HWTool.STORCLI]
        success, msg = self.hw_tool_helper.check_installed(mock_hw_available)
        self.assertTrue(success)
        self.assertEqual(msg, "")

    @mock.patch("hw_tools.os")
    @mock.patch("hw_tools.Path")
    def test_14_check_installed_not_okay(self, mock_os, mock_path):
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
        self.assertEqual(tools, {HWTool.SMARTCTL_EXPORTER})

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


@pytest.fixture
def snap_exporter():
    my_hw_tool = mock.MagicMock()
    my_hw_tool.value = "my-snap"

    class MySnapStrategy(SnapStrategy):
        channel = "my-channel/stable"
        _name = my_hw_tool

    strategy = MySnapStrategy()
    yield strategy


@pytest.fixture
def mock_snap_lib():
    with mock.patch("hw_tools.snap") as mock_snap:
        yield mock_snap
    mock_snap.reset_mock()


def test_snap_strategy_name(snap_exporter):
    assert snap_exporter.snap_name == "my-snap"


def test_snap_strategy_channel(snap_exporter):
    assert snap_exporter.channel == "my-channel/stable"


def test_snap_strategy_install_success(snap_exporter, mock_snap_lib):
    snap_exporter.install()
    mock_snap_lib.add.assert_called_once_with(
        snap_exporter.snap_name, channel=snap_exporter.channel
    )


def test_snap_strategy_install_fail(snap_exporter, mock_snap_lib):
    mock_snap_lib.add.side_effect = ValueError

    with pytest.raises(ValueError):
        snap_exporter.install()


def test_snap_strategy_remove_success(snap_exporter, mock_snap_lib):
    snap_exporter.remove()
    mock_snap_lib.remove.assert_called_once_with([snap_exporter.snap_name])


def test_snap_strategy_remove_fail(snap_exporter, mock_snap_lib):
    mock_snap_lib.remove.side_effect = ValueError

    with pytest.raises(ValueError):
        snap_exporter.remove()


@pytest.mark.parametrize(
    "services, expected",
    [
        # all services active
        (
            {
                "service_1": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": True,
                    "activators": [],
                },
                "service_2": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": True,
                    "activators": [],
                },
            },
            True,
        ),
        # at least one services down
        (
            {
                "service_1": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": False,
                    "activators": [],
                },
                "service_2": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": True,
                    "activators": [],
                },
            },
            False,
        ),
        # all services down
        (
            {
                "service_1": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": False,
                    "activators": [],
                },
                "service_2": {
                    "daemon": "simple",
                    "daemon_scope": "system",
                    "enabled": True,
                    "active": False,
                    "activators": [],
                },
            },
            False,
        ),
        # snap without service
        ({}, True),
    ],
)
def test_snap_strategy_check(snap_exporter, mock_snap_lib, services, expected):
    mock_snap_client = mock.MagicMock()
    mock_snap_client.services = services
    mock_snap_lib.SnapCache.return_value = {"my-snap": mock_snap_client}

    assert snap_exporter.check() is expected


@pytest.fixture
def mock_check_output():
    with mock.patch("hw_tools.subprocess.check_output") as mocked_check_output:
        yield mocked_check_output


@pytest.fixture
def mock_check_call():
    with mock.patch("hw_tools.subprocess.check_call") as mocked_check_call:
        yield mocked_check_call


@pytest.fixture
def mock_apt_lib():
    with mock.patch("hw_tools.apt") as mocked_apt_lib:
        yield mocked_apt_lib


@pytest.fixture
def mock_path():
    with mock.patch("hw_tools.Path") as mocked_path:
        yield mocked_path


@pytest.fixture
def mock_shutil_copy():
    with mock.patch("hw_tools.shutil.copy") as mocked_copy:
        yield mocked_copy


@pytest.fixture
def nvidia_driver_strategy(mock_check_output, mock_apt_lib, mock_path, mock_check_call):
    strategy = NVIDIADriverStrategy()
    strategy.installed_pkgs = mock_path
    yield strategy


@pytest.fixture
def dcgm_exporter_strategy(mock_snap_lib, mock_shutil_copy):
    yield DCGMExporterStrategy("latest/stable")


@mock.patch("hw_tools.DCGMExporterStrategy._create_custom_metrics")
def test_dcgm_exporter_install(mock_custom_metrics, dcgm_exporter_strategy):
    assert dcgm_exporter_strategy.install() is None
    mock_custom_metrics.assert_called_once()


def test_dcgm_create_custom_metrics(dcgm_exporter_strategy, mock_shutil_copy, mock_snap_lib):
    assert dcgm_exporter_strategy._create_custom_metrics() is None
    mock_shutil_copy.assert_called_once_with(
        Path.cwd() / "src/gpu_metrics/dcgm_metrics.csv", Path("/var/snap/dcgm/common")
    )
    dcgm_exporter_strategy.snap_client.set.assert_called_once_with(
        {"dcgm-exporter-metrics-file": "dcgm_metrics.csv"}
    )
    dcgm_exporter_strategy.snap_client.restart.assert_called_once_with(reload=True)


def test_dcgm_create_custom_metrics_copy_fail(
    dcgm_exporter_strategy, mock_shutil_copy, mock_snap_lib
):
    mock_shutil_copy.side_effect = FileNotFoundError
    with pytest.raises(FileNotFoundError):
        dcgm_exporter_strategy._create_custom_metrics()

    dcgm_exporter_strategy.snap_client.set.assert_not_called()
    dcgm_exporter_strategy.snap_client.restart.assert_not_called()


def test_nvidia_driver_strategy_install_success(
    mock_path, mock_check_output, mock_apt_lib, mock_check_call, nvidia_driver_strategy
):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = False
    mock_path.return_value = nvidia_version

    nvidia_driver_strategy.install()

    mock_apt_lib.add_package.assert_called_once_with("ubuntu-drivers-common", update_cache=True)
    mock_check_output.assert_called_once_with("ubuntu-drivers --gpgpu install".split(), text=True)
    mock_check_call.assert_called_once_with("modprobe nvidia".split())


def test_install_nvidia_drivers_already_installed(
    mock_path, mock_apt_lib, nvidia_driver_strategy, mock_check_output
):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = True
    mock_path.return_value = nvidia_version

    nvidia_driver_strategy.install()

    mock_apt_lib.add_package.assert_not_called()
    mock_check_output.assert_not_called()


def test_install_nvidia_drivers_nouveau_installed(mock_path, nvidia_driver_strategy, mock_apt_lib):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = False
    mock_path.return_value = nvidia_version
    mocked_open = mock.mock_open(read_data="nouveau")

    with mock.patch("builtins.open", mocked_open):
        with pytest.raises(ResourceInstallationError):
            nvidia_driver_strategy.install()

    mock_apt_lib.add_package.assert_not_called()
    mocked_open.assert_called_once_with("/proc/modules", encoding="utf-8")


def test_install_nvidia_drivers_subprocess_exception(
    mock_path, mock_check_output, mock_apt_lib, nvidia_driver_strategy
):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = False
    mock_path.return_value = nvidia_version
    mock_check_output.side_effect = subprocess.CalledProcessError(1, [])

    with pytest.raises(subprocess.CalledProcessError):
        nvidia_driver_strategy.install()

    mock_apt_lib.add_package.assert_called_once_with("ubuntu-drivers-common", update_cache=True)


def test_install_nvidia_drivers_no_drivers_found(
    mock_path, mock_check_output, mock_apt_lib, nvidia_driver_strategy
):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = False
    mock_path.return_value = nvidia_version
    mock_check_output.return_value = "No drivers found for installation"

    with pytest.raises(ResourceInstallationError):
        nvidia_driver_strategy.install()

    mock_apt_lib.add_package.assert_called_once_with("ubuntu-drivers-common", update_cache=True)


def test_nvidia_strategy_remove(nvidia_driver_strategy):
    assert nvidia_driver_strategy.remove() is None


@pytest.mark.parametrize("present, expected", [(True, True), (False, False)])
def test_nvidia_strategy_check(nvidia_driver_strategy, mock_path, present, expected):
    nvidia_version = mock.MagicMock()
    nvidia_version.exists.return_value = present
    mock_path.return_value = nvidia_version
    assert nvidia_driver_strategy.check() is expected


@mock.patch("hw_tools.Path.unlink")
@mock.patch("hw_tools.Path.exists")
@mock.patch("hw_tools.shutil")
@mock.patch("hw_tools.systemd")
def test_remove_legacy_smartctl_exporter_exist(
    mock_systemd, mock_shutil, mock_path_exists, mock_path_unlink
):
    mock_path_exists.return_value = True
    remove_legacy_smartctl_exporter()

    mock_systemd.service_stop.assert_called_once()
    mock_systemd.service_disable.assert_called_once()
    mock_path_unlink.assert_called()
    assert mock_path_unlink.call_count == 2
    mock_shutil.rmtree.assert_called_once()


@mock.patch("hw_tools.Path.unlink")
@mock.patch("hw_tools.Path.exists")
@mock.patch("hw_tools.shutil")
@mock.patch("hw_tools.systemd")
def test_remove_legacy_smartctl_exporter_not_exists(
    mock_systemd, mock_shutil, mock_path_exists, mock_path_unlink
):
    mock_path_exists.return_value = False
    remove_legacy_smartctl_exporter()

    mock_systemd.service_stop.assert_not_called()
    mock_systemd.service_disable.assert_not_called()
    mock_path_unlink.assert_not_called()
    mock_shutil.rmtree.assert_not_called()
