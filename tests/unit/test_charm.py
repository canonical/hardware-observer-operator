# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import json
import unittest
from unittest import mock

import ops
import ops.testing
from ops.model import ActiveStatus, BlockedStatus
from parameterized import parameterized
from redfish.rest.v1 import InvalidCredentialsError

import charm
from charm import ExporterError, HardwareObserverCharm
from config import HWTool


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(HardwareObserverCharm)
        self.addCleanup(self.harness.cleanup)

        get_bmc_address_patcher = mock.patch.object(charm, "get_bmc_address")
        self.mock_get_bmc_address = get_bmc_address_patcher.start()
        self.mock_get_bmc_address.return_value = "127.0.0.1"
        self.addCleanup(get_bmc_address_patcher.stop)

        bmc_hw_verifier_patcher = mock.patch.object(charm, "bmc_hw_verifier")
        self.mock_bmc_hw_verifier = bmc_hw_verifier_patcher.start()
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
            HWTool.REDFISH,
        ]
        self.addCleanup(bmc_hw_verifier_patcher.stop)

        redfish_client_patcher = mock.patch("charm.redfish_client")
        redfish_client_patcher.start()
        self.addCleanup(redfish_client_patcher.stop)

        requests_patcher = mock.patch("hw_tools.requests")
        requests_patcher.start()
        self.addCleanup(requests_patcher.stop)

    @classmethod
    def setUpClass(cls):
        pass

    def _get_notice_count(self, hook):
        """Return the notice count for a given charm hook."""
        notice_count = 0
        handle = f"HardwareObserverCharm/on/{hook}"
        for event_path, _, _ in self.harness.charm.framework._storage.notices(None):
            if event_path.startswith(handle):
                notice_count += 1
        return notice_count

    def test_harness(self) -> None:
        """Test charm initialize."""
        self.harness.begin()
        self.assertFalse(self.harness.charm._stored.resource_installed)

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_install(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test install event handler."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        self.harness.charm.exporter.install.assert_called_once()
        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_upgrade_charm(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test upgrade_charm event handler."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        self.harness.charm.exporter.install.assert_called_once()
        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

        self.harness.charm.unit.status = ActiveStatus("Install complete")

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_install_missing_resources(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test install event handler when resources are missing."""
        mock_hw_tool_helper.return_value.install.return_value = (
            False,
            "Missing resources: ['storcli-deb']",
        )
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Missing resources: ['storcli-deb']")
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_install_redfish_unavailable(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test install event handler when redfish is unavailable."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        self.harness.charm.exporter.install.assert_called_with(
            10200,  # default in config.yaml
            "INFO",  # default in config.yaml
            {},
            10,  # default int config.yaml
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_exporter_install_fail(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test exporter install failure."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = False
        self.harness.begin()
        self.harness.charm.validate_exporter_configs = mock.Mock()
        self.harness.charm.validate_exporter_configs.return_value = (False, "error")
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Failed to install exporter, please refer to `juju debug-log`"),
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_update_status_all_green(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status event handler when everything is okay."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_update_status_check_installed_false(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status event handler when hw tool checks failed."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (False, "error")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("error"))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_update_status_exporter_crashed(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.check_health.return_value = False
        mock_exporter.return_value.restart.side_effect = Exception()
        self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        with self.assertRaises(ExporterError):
            self.harness.charm.on.update_status.emit()

    @mock.patch.object(charm, "bmc_hw_verifier", return_value=[])
    @mock.patch("charm.HWToolHelper")
    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_config_changed(self, mock_exporter, mock_hw_tool_helper, mock_bmc_hw_verifier):
        """Test config change event renders config file."""
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm.num_cos_agent_relations = 1  # exporter enabled
        self.harness.charm.hw_tool_helper.check_installed.return_value = (
            True,
            "",
        )  # hw tool install ok

        new_config = {"exporter-port": 80, "exporter-log-level": "DEBUG"}
        self.harness.update_config(new_config)
        self.harness.charm.on.config_changed.emit()

        self.harness.charm.exporter.template.render_config.assert_called()

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

    @mock.patch.object(charm, "bmc_hw_verifier", return_value=[])
    @mock.patch("charm.HWToolHelper")
    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_config_changed_without_cos_agent_relation(
        self, mock_exporter, mock_hw_tool_helper, mock_bmc_hw_verifier
    ):
        """Test config change event don't render config file if cos_agent relation is missing."""
        self.harness.begin()
        self.harness.charm._stored.resource_installed = True
        self.harness.charm.num_cos_agent_relations = 0  # exporter disabled
        self.harness.charm.hw_tool_helper.check_installed.return_value = (
            True,
            "",
        )  # hw tool install ok

        new_config = {"exporter-port": 80, "exporter-log-level": "DEBUG"}
        self.harness.update_config(new_config)
        self.harness.charm.on.config_changed.emit()

        self.harness.charm.exporter.template.render_config.assert_not_called()

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Missing relation: [cos-agent]")
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_config_changed_before_install_complete(self, mock_exporter):
        """Test config change event is deferred if charm not installed."""
        self.harness.begin()
        self.harness.charm._stored.resource_installed = False

        self.harness.charm.on.config_changed.emit()
        self.assertEqual(self._get_notice_count("config_changed"), 1)

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_upgrade_force_reconfig_exporter(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test upgrade event handler will reconfigure exporter."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm._stored.exporter_installed = True
        print(dir(self.harness.charm.on))
        self.harness.charm.on.upgrade_charm.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)
        self.assertTrue(self.harness.charm._stored.exporter_installed)

        self.harness.charm.exporter.install.assert_called_once()
        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_update_status_config_invalid(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status event handler when config is invalid."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.harness.charm.validate_exporter_configs = mock.MagicMock()
        self.harness.charm.validate_exporter_configs.return_value = (False, "config fail message")

        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("config fail message"))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_config_changed_update_alert_rules(self, mock_hw_tool_helper, mock_exporter):
        """Test config changed will update alert rule."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

        relation_data = self.harness.get_relation_data(rid, "hardware-observer/0")
        metrics_alert_rules = json.loads(relation_data["config"]).get("metrics_alert_rules")

        with mock.patch(
            "charm.COSAgentProvider._metrics_alert_rules", new_callable=mock.PropertyMock
        ) as mock_alert_rules:
            fake_metrics_alert_rules = {}
            mock_alert_rules.return_value = fake_metrics_alert_rules
            self.harness.charm.on.config_changed.emit()

        relation_data = self.harness.get_relation_data(rid, "hardware-observer/0")
        updated_metrics_alert_rules = json.loads(relation_data["config"]).get(
            "metrics_alert_rules"
        )
        self.assertEqual(updated_metrics_alert_rules, fake_metrics_alert_rules)
        self.assertNotEqual(updated_metrics_alert_rules, metrics_alert_rules)

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_upgrade_charm_update_alert_rules(self, mock_hw_tool_helper, mock_exporter):
        """Test upgrade charm event updates alert rule."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

        relation_data = self.harness.get_relation_data(rid, "hardware-observer/0")
        metrics_alert_rules = json.loads(relation_data["config"]).get("metrics_alert_rules")

        with mock.patch(
            "charm.COSAgentProvider._metrics_alert_rules", new_callable=mock.PropertyMock
        ) as mock_alert_rules:
            fake_metrics_alert_rules = {}
            mock_alert_rules.return_value = fake_metrics_alert_rules
            self.harness.charm.on.upgrade_charm.emit()

        relation_data = self.harness.get_relation_data(rid, "hardware-observer/0")
        updated_metrics_alert_rules = json.loads(relation_data["config"]).get(
            "metrics_alert_rules"
        )
        self.assertEqual(updated_metrics_alert_rules, fake_metrics_alert_rules)
        self.assertNotEqual(updated_metrics_alert_rules, metrics_alert_rules)

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_install_redfish_enabled_with_correct_credential(
        self, mock_hw_tool_helper, mock_exporter
    ) -> None:
        """Test install event when redfish is available and credential is correct."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.REDFISH,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        self.harness.charm.exporter.install.assert_called_with(
            10200,  # default in config.yaml
            "INFO",  # default in config.yaml
            self.harness.charm.get_redfish_conn_params(),
            10,  # default int config.yaml
        )

    @parameterized.expand([(InvalidCredentialsError), (Exception)])
    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    @mock.patch("charm.redfish_client", return_value=mock.MagicMock())
    def test_install_redfish_enabled_with_incorrect_credential(
        self, test_exception, mock_redfish_client, mock_hw_tool_helper, mock_exporter
    ) -> None:
        """Test event install when redfish is available but credential is wrong."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.REDFISH,
        ]
        mock_redfish_client.side_effect = test_exception()
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.resource_installed)

        # ensure exporter is installed (not started/enabled)
        # even when redfish credentials are wrong
        mock_exporter.return_value.install.assert_called_once()
        mock_exporter.reset_mock()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Invalid config: 'redfish-username' or 'redfish-password'"),
        )

    @parameterized.expand([(InvalidCredentialsError), (Exception)])
    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    @mock.patch("charm.redfish_client", return_value=mock.MagicMock())
    def test_config_changed_redfish_enabled_with_incorrect_credential(
        self, test_exception, mock_redfish_client, mock_hw_tool_helper, mock_exporter
    ) -> None:
        """Test event config changed when redfish is available but credential is wrong."""
        self.mock_bmc_hw_verifier.return_value = [
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
            HWTool.REDFISH,
        ]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        mock_redfish_client.side_effect = test_exception()
        new_config = {
            "exporter-port": 80,
            "exporter-log-level": "DEBUG",
            "redfish-username": "redfish",
            "redfish-password": "redfish",
        }
        self.harness.update_config(new_config)
        self.harness.charm.on.config_changed.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Invalid config: 'redfish-username' or 'redfish-password'"),
        )
