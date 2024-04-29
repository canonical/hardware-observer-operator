# Copyright 2024 Canotical Ltd.
# See LICENSE file for licensing details.

import pathlib
import unittest
from unittest import mock
import yaml

import charm
import service
from config import (
    HARDWARE_EXPORTER_SETTINGS,
    HWTool,
)


class TestExporter(unittest.TestCase):
    """Test Base Exporter methods."""

    def setUp(self) -> None:
        """Set up harness for each test case."""
        systemd_lib_patcher = mock.patch.object(service, "systemd")
        self.mock_systemd = systemd_lib_patcher.start()
        self.addCleanup(systemd_lib_patcher.stop)

        hw_tool_lib_patcher = mock.patch.object(charm, "HWToolHelper")
        mock_hw_tool_helper = hw_tool_lib_patcher.start()
        mock_hw_tool_helper.return_value.install.return_value = [True, ""]
        mock_hw_tool_helper.return_value.check_installed.return_value = [True, ""]
        self.addCleanup(hw_tool_lib_patcher.stop)

        get_bmc_address_patcher = mock.patch("service.get_bmc_address", return_value="127.0.0.1")
        get_bmc_address_patcher.start()
        self.addCleanup(get_bmc_address_patcher.stop)

        get_charm_hw_tool_enable_list_patcher = mock.patch(
            "charm.get_hw_tool_enable_list",
            return_value=[HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH],
        )
        get_charm_hw_tool_enable_list_patcher.start()
        self.addCleanup(get_charm_hw_tool_enable_list_patcher.stop)

        os_patcher = mock.patch.object(service, "os")
        os_patcher.start()
        self.addCleanup(os_patcher.stop)

        search_path = pathlib.Path(f"{__file__}/../../..").resolve()
        self.mock_config = {
            "hardware-exporter-port": 10200,
            "collect-timeout": 10,
            "exporter-log-level": "INFO",
            "redfish-username": "",
            "redfish-password": "",
        }
        self.mock_stored_hw_tool_list_values = ["storcli", "ssacli"]

        service.BaseExporter.__abstractmethods__ = set()
        self.exporter = service.BaseExporter(
            search_path, self.mock_config, HARDWARE_EXPORTER_SETTINGS
        )  # Any setting could be used here.

    def test_install_okay(self):
        """Test exporter install method."""
        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            self.exporter.install()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    def test_install_failed_rendering(self):
        """Test exporter install method when rendering fails."""
        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            mock_open.side_effect = NotADirectoryError()
            self.exporter.install()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_uninstall_okay(self, mock_service_exists):
        """Test exporter uninstall method."""
        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            self.exporter.uninstall()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_uninstall_failed(self, mock_service_exists):
        """Test exporter uninstall method with permission error."""
        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            mock_unlink.side_effect = PermissionError()
            self.exporter.uninstall()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

    def test_enable_and_start(self):
        """Test exporter enable and start behavior."""
        self.exporter.enable_and_start()
        self.mock_systemd.service_enable.assert_called_once()
        self.mock_systemd.service_start.assert_called_once()

    def test_disable_and_stop(self):
        """Test exporter disable and stop behavior."""
        self.exporter.disable_and_stop()
        self.mock_systemd.service_disable.assert_called_once()
        self.mock_systemd.service_stop.assert_called_once()


class TestHardwareExporter(unittest.TestCase):
    """Test Hardware Exporter's methods."""

    def setUp(self) -> None:
        """Set up harness for each test case."""
        systemd_lib_patcher = mock.patch.object(service, "systemd")
        self.mock_systemd = systemd_lib_patcher.start()
        self.addCleanup(systemd_lib_patcher.stop)

        hw_tool_lib_patcher = mock.patch.object(charm, "HWToolHelper")
        mock_hw_tool_helper = hw_tool_lib_patcher.start()
        mock_hw_tool_helper.return_value.install.return_value = [True, ""]
        mock_hw_tool_helper.return_value.check_installed.return_value = [True, ""]
        self.addCleanup(hw_tool_lib_patcher.stop)

        get_bmc_address_patcher = mock.patch("service.get_bmc_address", return_value="127.0.0.1")
        get_bmc_address_patcher.start()
        self.addCleanup(get_bmc_address_patcher.stop)

        get_charm_hw_tool_enable_list_patcher = mock.patch(
            "charm.get_hw_tool_enable_list",
            return_value=[HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH],
        )
        get_charm_hw_tool_enable_list_patcher.start()
        self.addCleanup(get_charm_hw_tool_enable_list_patcher.stop)

        os_patcher = mock.patch.object(service, "os")
        os_patcher.start()
        self.addCleanup(os_patcher.stop)

        search_path = pathlib.Path(f"{__file__}/../../..").resolve()
        self.mock_config = {
            "hardware-exporter-port": 10200,
            "collect-timeout": 10,
            "exporter-log-level": "INFO",
            "redfish-username": "",
            "redfish-password": "",
        }
        self.mock_stored_hw_tool_list_values = ["storcli", "ssacli"]
        self.exporter = service.HardwareExporter(
            search_path, self.mock_config, self.mock_stored_hw_tool_list_values
        )

    def test_render_config_content(self):
        """Test render config content."""
        content = self.exporter._render_config_content()
        content_config = yaml.safe_load(content)
        self.assertEqual(content_config["port"], 10200)
        self.assertEqual(content_config["level"], "INFO")
        self.assertEqual(content_config["collect_timeout"], 10)
        self.assertEqual(
            content_config["enable_collectors"], ["collector.mega_raid", "collector.hpe_ssa"]
        )

    def test_get_redfish_conn_params_when_redfish_is_available(self):
        """Test get_redfish_conn_params when Redfish is available."""
        self.exporter.enabled_hw_tool_list = ["redfish"]
        result = self.exporter.get_redfish_conn_params(self.mock_config)
        expected_result = {
            "host": "https://127.0.0.1",
            "username": "",
            "password": "",
            "timeout": 10,
        }
        self.assertEqual(result, expected_result)

    def test_get_redfish_conn_params_when_redfish_is_unavailable(self):
        """Test get_redfish_conn_params when Redfish is not available."""
        self.exporter.enabled_hw_tool_list = ["ssacli"]
        result = self.exporter.get_redfish_conn_params(self.mock_config)
        expected_result = {}
        self.assertEqual(result, expected_result)
