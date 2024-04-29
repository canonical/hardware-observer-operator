# Copyright 2023 Canotical Ltd.
# See LICENSE file for licensing details.

import pathlib
import unittest
from unittest import mock

import ops
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness
from parameterized import parameterized

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
        mock_hw_tool_helper = hw_tool_lib_patcher.start()
        mock_hw_tool_helper.return_value.install.return_value = [True, ""]
        mock_hw_tool_helper.return_value.check_installed.return_value = [True, ""]
        self.addCleanup(hw_tool_lib_patcher.stop)

        get_bmc_address_patcher = mock.patch("charm.get_bmc_address", return_value="127.0.0.1")
        get_bmc_address_patcher.start()
        self.addCleanup(get_bmc_address_patcher.stop)

        get_charm_hw_tool_enable_list_patcher = mock.patch(
            "charm.get_hw_tool_enable_list",
            return_value=[HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH],
        )
        get_charm_hw_tool_enable_list_patcher.start()
        self.addCleanup(get_charm_hw_tool_enable_list_patcher.stop)

        redfish_client_patcher = mock.patch("charm.redfish_client")
        redfish_client_patcher.start()
        self.addCleanup(redfish_client_patcher.stop)

        os_patcher = mock.patch.object(service, "os")
        os_patcher.start()
        self.addCleanup(os_patcher.stop)

    @classmethod
    def setUpClass(cls):
        exporter_health_retry_count_patcher = mock.patch("charm.EXPORTER_HEALTH_RETRY_COUNT", 1)
        exporter_health_retry_count_patcher.start()
        cls.addClassCleanup(exporter_health_retry_count_patcher.stop)

        exporter_health_retry_timeout_patcher = mock.patch(
            "charm.EXPORTER_HEALTH_RETRY_TIMEOUT", 0
        )
        exporter_health_retry_timeout_patcher.start()
        cls.addClassCleanup(exporter_health_retry_timeout_patcher.stop)

    def test_install_okay(self):
        """Test exporter service is installed when charm is installed - okay."""
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open) as mock_open:
            self.harness.charm.on.install.emit()
            mock_open.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    def test_install_failed_rendering(self):
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
    def test_uninstall_okay(self, mock_service_exists):
        """Test exporter service is uninstalled when charm is removed - okay."""
        self.harness.begin()

        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            self.harness.charm.on.remove.emit()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_uninstall_failed(self, mock_service_exists):
        """Test exporter service is not uninstalled - failed to remove."""
        self.harness.begin()

        with mock.patch.object(pathlib.Path, "unlink") as mock_unlink:
            mock_unlink.side_effect = PermissionError()
            self.harness.charm.on.remove.emit()
            mock_unlink.assert_called()
            self.mock_systemd.daemon_reload.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_start_okay(self, mock_service_installed):
        """Test exporter service started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm._stored.exporter_installed = True
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_called_once()
        self.mock_systemd.service_enable.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=False)
    def test_start_failed(self, mock_service_not_installed):
        """Test exporter service failed to started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_not_called()
        self.mock_systemd.service_enable.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_start_defer_resource_not_ready(self, mock_service_installed):
        """Test exporter service started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = False
        self.harness.charm._stored.exporter_installed = True
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_not_called()
        self.mock_systemd.service_enable.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_start_defer_exporter_not_ready(self, mock_service_installed):
        """Test exporter service started when relation is joined."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm._stored.exporter_installed = False
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_start.assert_not_called()
        self.mock_systemd.service_enable.assert_not_called()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_stop_okay(self, mock_service_installed):
        """Test exporter service is stopped when service is installed and relation is departed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm._stored.exporter_installed = True
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.remove_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_stop.assert_called_once()
        self.mock_systemd.service_disable.assert_called_once()

    @mock.patch.object(pathlib.Path, "exists", return_value=False)
    def test_stop_failed(self, mock_service_not_installed):
        """Test exporter service failed to stop when service is not installed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm._stored.exporter_installed = True
        with self.assertRaises(service.ExporterError):
            self.harness.add_relation_unit(rid, "grafana-agent/0")
        with self.assertRaises(service.ExporterError):
            self.harness.remove_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_stop.assert_not_called()
        self.mock_systemd.service_disable.assert_not_called()

    @parameterized.expand(
        [
            (False, ActiveStatus("Unit is ready"), True),
            (True, ActiveStatus("Unit is ready"), True),
            (False, ActiveStatus("Unit is ready"), False),
        ]
    )
    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_check_health(
        self,
        failed,
        expected_status,
        restart_okay,
        mock_service_installed,
    ):
        """Test check_health function when service is installed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        with mock.patch("builtins.open", new_callable=mock.mock_open) as _:
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.mock_systemd.service_running.return_value = restart_okay
        self.mock_systemd.service_failed.return_value = failed
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, expected_status)

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_check_health_exporter_crash(self, mock_service_installed):
        """Test check_health function when service is installed but exporter crashes."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        with mock.patch("builtins.open", new_callable=mock.mock_open) as _:
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.mock_systemd.service_running.return_value = False
        self.mock_systemd.service_failed.return_value = True
        with self.assertRaises(service.ExporterError):
            self.harness.charm.on.update_status.emit()

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_check_relation_exists(self, mock_service_installed):
        """Test check_relation function when relation exists."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        with mock.patch("builtins.open", new_callable=mock.mock_open) as _:
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.mock_systemd.service_failed.return_value = False
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_check_relation_not_exists(self, mock_service_installed):
        """Test check_relation function when relation does not exists."""
        self.harness.begin()
        with mock.patch("builtins.open", new_callable=mock.mock_open) as _:
            self.harness.charm.on.install.emit()
        self.mock_systemd.service_failed.return_value = False
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Missing relation: [cos-agent]")
        )

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_too_many_relations(self, mock_service_installed):
        """Test there too many relations."""
        rid_1 = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        rid_2 = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()
        with mock.patch("builtins.open", new_callable=mock.mock_open) as _:
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid_1, "grafana-agent/0")
            self.harness.add_relation_unit(rid_2, "grafana-agent/1")
        self.mock_systemd.service_failed.return_value = False
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Cannot relate to more than one grafana-agent"),
        )

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_config_changed_log_level_okay(self, mock_service_installed):
        """Test on_config_change function when exporter-log-level is changed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open):
            self.mock_systemd.service_failed.return_value = False
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "grafana-agent/0")
            # this will trigger config changed event
            self.harness.update_config({"exporter-log-level": "DEBUG"})
            self.mock_systemd.service_restart.assert_called_once()
            self.assertEqual(
                self.harness.charm.unit.status,
                ActiveStatus("Unit is ready"),
            )

    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_invalid_exporter_log_level(self, mock_service_installed):
        """Test on_config_change function when exporter-log-level is changed."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open):
            self.mock_systemd.service_failed.return_value = False
            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "grafana-agent/0")
            # self.harness.charm.validate_exporter_configs = mock.Mock()
            # self.harness.charm.validate_exporter_configs.return_value = (False, "error")
            self.harness.update_config({"exporter-port": 102000, "exporter-log-level": "DEBUG"})
            self.harness.charm.on.config_changed.emit()
            self.assertEqual(
                self.harness.charm.unit.status, BlockedStatus("Invalid config: 'exporter-port'")
            )
            self.harness.update_config({"exporter-port": 8080, "exporter-log-level": "xxx"})
            self.harness.charm.on.config_changed.emit()
            self.assertEqual(
                self.harness.charm.unit.status,
                BlockedStatus("Invalid config: 'exporter-log-level'"),
            )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch.object(pathlib.Path, "exists", return_value=True)
    def test_render_config_fail(self, mock_service_installed, mock_exporter):
        """Test on_config_change function when render config fails."""
        rid = self.harness.add_relation(EXPORTER_RELATION_NAME, "grafana-agent")
        self.harness.begin()

        with mock.patch("builtins.open", new_callable=mock.mock_open):
            self.mock_systemd.service_failed.return_value = False
            mock_exporter.return_value.install.return_value = True
            self.harness.charm.on.install.emit()
            mock_exporter.return_value.template.render_config.return_value = False
            self.harness.add_relation_unit(rid, "grafana-agent/0")
            self.harness.charm.on.config_changed.emit()
            self.mock_systemd.service_restart.assert_not_called()
            self.assertEqual(
                self.harness.charm.unit.status,
                BlockedStatus(
                    "Failed to configure exporter, please check if the server is healthy."
                ),
            )


class TestExporterTemplate(unittest.TestCase):
    def setUp(self):
        """Set up harness for each test case."""
        search_path = pathlib.Path(f"{__file__}/../../..").resolve()
        self.template = service.ExporterTemplate(search_path)

    def test_render_config(self):
        with mock.patch.object(self.template, "_install") as mock_install:
            self.template.render_config(
                port="80",
                level="info",
                redfish_conn_params={},
                collect_timeout=10,
                hw_tools=[HWTool.STORCLI, HWTool.SSACLI],
            )
            mock_install.assert_called_with(
                EXPORTER_CONFIG_PATH,
                self.template.config_template.render(
                    PORT="80",
                    LEVEL="info",
                    COLLECT_TIMEOUT=10,
                    COLLECTORS=["collector.mega_raid", "collector.hpe_ssa"],
                    REDFISH_ENABLE=False,
                    REDFISH_HOST="",
                    REDFISH_PASSWORD="",
                    REDFISH_USERNAME="",
                    REDFISH_CLIENT_TIMEOUT=10,
                ),
                mode=0o600,
            )

    def test_render_config_redfish(self):
        with mock.patch.object(self.template, "_install") as mock_install:
            self.template.render_config(
                port="80",
                level="info",
                collect_timeout=10,
                redfish_conn_params={
                    "host": "127.0.0.1",
                    "username": "default_user",
                    "password": "default_pwd",
                    "timeout": 10,
                },
                hw_tools=[HWTool.REDFISH],
            )
            mock_install.assert_called_with(
                EXPORTER_CONFIG_PATH,
                self.template.config_template.render(
                    PORT="80",
                    LEVEL="info",
                    COLLECT_TIMEOUT=10,
                    COLLECTORS=["collector.redfish"],
                    REDFISH_ENABLE=True,
                    REDFISH_HOST="127.0.0.1",
                    REDFISH_PASSWORD="default_pwd",
                    REDFISH_USERNAME="default_user",
                    REDFISH_CLIENT_TIMEOUT="10",
                ),
                mode=0o600,
            )
