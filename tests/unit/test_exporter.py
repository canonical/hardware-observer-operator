"""Tests for exporter."""
import unittest
from unittest import mock

from charms.operator_libs_linux.v2 import snap

from config import EXPORTER_NAME
from exporter import Exporter, check_snap_installed


class TestCheckSnapInstalled(unittest.TestCase):
    """Test decroator check_snap_installed."""

    @mock.patch("exporter.snap.SnapCache")
    def test_01_check_snap_installed(self, mock_snapcache):
        """If exporter not exists.

        - The exporter should be assigned.
        - The func should be called.
        """
        mock_func = mock.MagicMock()
        mock_func.__name__ = "mock_func"
        wrapper = check_snap_installed(mock_func)

        mock_self = mock.MagicMock()
        mock_self._exporter = None
        mock_args = [mock.MagicMock(), mock.MagicMock()]
        mock_kwargs = {"a": mock.MagicMock(), "b": mock.MagicMock()}

        mock_snap_obj = mock.MagicMock()
        mock_snapcache.return_value = {EXPORTER_NAME: mock_snap_obj}
        mock_snap_obj.present = True

        wrapper(mock_self, *mock_args, **mock_kwargs)

        mock_func.assert_called_with(mock_self, *mock_args, **mock_kwargs)
        assert mock_self._exporter == mock_snapcache().get(EXPORTER_NAME)

    @mock.patch("exporter.snap.SnapCache", return_value={})
    def test_02_check_snap_installed_error_handling(self, mock_snapcache):
        """Test error handling.

        - The snap.SnapNotFoundError should be handled.
        """
        mock_func = mock.MagicMock()
        mock_func.__name__ = "mock_func"
        wrapper = check_snap_installed(mock_func)

        mock_self = mock.MagicMock()
        mock_self._exporter = None
        mock_args = [mock.MagicMock(), mock.MagicMock()]
        mock_kwargs = {"a": mock.MagicMock(), "b": mock.MagicMock()}

        mock_snap_obj = mock.MagicMock()
        mock_snapcache.return_value = {}
        mock_snap_obj.present = None

        wrapper(mock_self, *mock_args, **mock_kwargs)

        mock_func.assert_not_called()


def patch_snap_installed():
    mock_snap = mock.Mock()
    mock_snap.present = True
    mock_snap.services = {EXPORTER_NAME: {"active": True}}
    return mock.patch(
        "charms.operator_libs_linux.v2.snap.SnapCache",
        return_value={EXPORTER_NAME: mock_snap},
    )


class TestExporter(unittest.TestCase):
    def setUp(self):
        mock_charm = mock.MagicMock()
        key = "fake-key"

        self.mock_charm = mock_charm
        self.key = key

    def test_01_init(self):
        exporter = Exporter(self.mock_charm, self.key)

        self.assertTrue(exporter._exporter is None)
        self.assertTrue(exporter._charm == self.mock_charm)
        self.assertTrue(exporter._stored == self.mock_charm._stored)

    @mock.patch("exporter.snap")
    def test_02_install_or_refresh_install_from_local(self, mock_snap):
        """Test install_or_refresh.

        - If channel provided in charm._stored, the snap should be
            install locally.
        """
        channel = "stable"
        self.mock_charm._stored.config = {
            "exporter-channel": channel,
            "exporter-snap": "exporter-snap-content",
        }
        exporter = Exporter(self.mock_charm, self.key)

        exporter.install_or_refresh()

        mock_snap.install_local.assert_called_with("exporter-snap-content", dangerous=True)

    @mock.patch("exporter.snap")
    def test_03_install_or_refresh_install_from_snapcraft(self, mock_snap):
        """Test install_or_refresh.

        - If channel provided with argument, the snap should be install
            from snapcraft.
        """
        channel = "stable"
        self.mock_charm._stored.config = {}
        exporter = Exporter(self.mock_charm, self.key)
        mock_snap.SnapError = snap.SnapError

        exporter.install_or_refresh(channel)

        mock_snap.add.assert_called_with([EXPORTER_NAME], channel=channel)

    @mock.patch("exporter.snap")
    def test_04_install_or_refresh_error_handling(self, mock_snap):
        """The snap.SnapError should be handled."""
        channel = "stable"
        self.mock_charm._stored.config = {}
        exporter = Exporter(self.mock_charm, self.key)
        mock_snap.SnapError = snap.SnapError
        mock_snap.add.side_effect = snap.SnapError()

        exporter.install_or_refresh(channel)

        mock_snap.add.assert_called_with([EXPORTER_NAME], channel=channel)

    @mock.patch("exporter.Exporter.install_or_refresh")
    def test_05_on_config_changed(self, mock_install_or_refresh):
        """Test on_config_changed."""
        mock_charm = mock.MagicMock()
        key = "fake-key"
        exporter = Exporter(mock_charm, key)

        for change_set in [
            set({"exporter-snap"}),
            set({"exporter-channel"}),
        ]:
            exporter.on_config_changed(change_set)

            # 2 should be change to 1 after we remove the testing
            # self.install_or_refresh line.
            mock_install_or_refresh.call_count == 2

    @patch_snap_installed()
    def test_06_start(self, mock_snap_cache):
        """Test start."""
        exporter = Exporter(self.mock_charm, self.key)
        mock_exporter = mock.MagicMock(spec=snap.Snap)
        exporter._exporter = mock_exporter
        exporter.start()
        mock_exporter.start.assert_called_once()
