# Copyright 2023 Canotical Ltd.
# See LICENSE file for licensing details.

import pathlib
import unittest
from unittest import mock

import ops
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

import charm
import service
from charm import HardwareObserverCharm
from config import EXPORTER_CONFIG_PATH, HWTool

ops.testing.SIMULATE_CAN_CONNECT = True

EXPORTER_RELATION_NAME = "cos-agent"


class TestExporter(unittest.TestCase):
    """Test Exporter's methods."""

    def setUp(self):
        """Set up harness for each test case."""
        self.harness = Harness(HardwareObserverCharm)
        self.addCleanup(self.harness.cleanup)

        systemd_lib_patcher = mock.patch.object(service, "systemd")
        self.mock_systemd = systemd_lib_patcher.start()
        self.addCleanup(systemd_lib_patcher.stop)

        hw_tool_lib_patcher = mock.patch.object(charm, "HWToolHelper")
        hw_tool_lib_patcher.start()
        self.addCleanup(hw_tool_lib_patcher.stop)

        get_hw_tool_white_list_patcher = mock.patch.object(service, "get_hw_tool_white_list")
        get_hw_tool_white_list_patcher.start()
        self.addCleanup(get_hw_tool_white_list_patcher.stop)

    def test_00_install_okay(self):
        """Test exporter service is installed when charm is installed - okay."""
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            self.harness.charm.on.install.emit()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    def test_01_install_failed_rendering(self):
        """Test exporter service is failed to installed - failed to render."""
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            mock_open.side_effect = NotADirectoryError()
            self.harness.charm.on.install.emit()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            mock_open.side_effect = PermissionError()
            self.harness.charm.on.install.emit()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_10_uninstall_okay(self, mock_service_exists):
        """Test exporter service is uninstalled when charm is removed - okay."""
        self.harness.begin()

        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            self.harness.charm.on.remove.emit()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_11_uninstall_failed(self, mock_service_exists):
        """Test exporter service is not uninstalled - failed to remove."""
        self.harness.begin()

        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            mock_unlink.side_effect = PermissionError()
            self.harness.charm.on.remove.emit()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_20_start_okay(self, mock_service_installed):
        """Test exporter service started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=False)
    def test_21_start_failed(self, mock_service_not_installed):
        """Test exporter service failed to started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_30_stop_okay(self, mock_service_installed):
        """Test exporter service is stopped when service is installed and relation is departed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.remove_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_stop.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=False)
    def test_31_stop_failed(self, mock_service_not_installed):
        """Test exporter service failed to stop when service is not installed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.remove_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_stop.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_40_check_health(self, mock_service_installed):
        """Test check_health function when service is installed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        test_cases = [
            (False, ActiveStatus("Unit is ready")),
            (True, BlockedStatus("Exporter is unhealthy")),
        ]
        for failed, expected_status in test_cases:
            with self.subTest(service_failed=failed):
                self.mock_systemd.service_failed.return_value = failed
                self.harness.charm.on.update_status.emit()
                self.assertEqual(self.harness.charm.unit.status, expected_status)

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_41_check_active(self, mock_service_installed):
        """Test check_health function when service is installed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        test_cases = [
            (True, ActiveStatus("Unit is ready")),
            (False, BlockedStatus("Exporter is not running")),
        ]
        self.mock_systemd.service_failed.return_value = False
        for running, expected_status in test_cases:
            with self.subTest(service_running=running):
                self.mock_systemd.service_running.return_value = running
                self.harness.charm.on.update_status.emit()
                self.assertEqual(self.harness.charm.unit.status, expected_status)

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_50_check_relation_exists(self, mock_service_installed):
        """Test check_relation function when relation exists."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "cos-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_failed.return_value = False
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_51_check_relation_not_exists(self, mock_service_installed):
        """Test check_relation function when relation does not exists."""
        self.harness.begin()
        self.mock_systemd.service_failed.return_value = False
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Missing relation: [cos-agent]")
        )

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_60_config_changed_log_level_okay(self, mock_service_installed):
        """Test on_config_change function when exporter-log-level is changed."""
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open):
            self.mock_systemd.service_failed.return_value = False
            self.harness.charm.on.install.emit()
            self.harness.update_config({"exporter-log-level": "DEBUG"})
            self.harness.charm.on.config_changed.emit()
            self.assertEqual(self.harness.charm._stored.config.get("exporter-log-level"), "DEBUG")
            self.mock_systemd.service_restart.assert_called_once()


class TestExporterTemplate(unittest.TestCase):
    def setUp(self):
        """Set up harness for each test case."""
        search_path = pathlib.Path(f"{__file__}/../../..").resolve()
        self.template = service.ExporterTemplate(search_path)

    @mock.patch(
        "service.get_hw_tool_white_list",
        return_value=[HWTool.STORCLI, HWTool.SSACLI],
    )
    def test_render_config(self, mock_get_hw_tool_white_list):
        # mock_config_template = mock.Mock()
        # self.template.config_template = mock_config_template

        with mock.patch.object(self.template, "_install") as mock_install:
            self.template.render_config(
                port="80",
                level="info",
                redfish_creds={"host": "", "username": "", "password": ""},
            )
        mock_install.assert_called_with(
            EXPORTER_CONFIG_PATH,
            self.template.config_template.render(
                PORT="80",
                LEVEL="info",
                COLLECTORS=["collector.mega_raid", "collector.hpe_ssa"],
                redfish_creds={"host": "", "username": "", "password": ""},
            ),
        )
