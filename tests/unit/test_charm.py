# Copyright 2023 jneo8
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest import mock

import ops
import ops.testing
from ops.model import ActiveStatus, BlockedStatus, ErrorStatus

import charm
from charm import HardwareObserverCharm
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
        self.mock_bmc_hw_verifier.return_value = [HWTool.IPMI, HWTool.REDFISH]
        self.addCleanup(bmc_hw_verifier_patcher.stop)

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

    def test_01_harness(self) -> None:
        """Test charm initialise."""
        self.harness.begin()
        self.assertFalse(self.harness.charm._stored.installed)
        self.assertTrue(isinstance(self.harness.charm._stored.config, ops.framework.StoredDict))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_02_install(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test event install."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        self.harness.charm.exporter.install.assert_called_once()
        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_03_upgrade_charm(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test event upgrade_charm."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        self.harness.charm.exporter.install.assert_called_once()
        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

        self.harness.charm.unit.status = ActiveStatus("Install complete")

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_04_install_missing_resources(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test event install."""
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
    def test_05_install_redfish_unavailable(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test event install."""
        self.mock_bmc_hw_verifier.return_value = [HWTool.IPMI]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        self.harness.charm.exporter.install.assert_called_with(10000, "INFO", {})

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_06_install_failed(self, mock_hw_tool_helper, mock_exporter) -> None:
        """Test event install."""
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_exporter.return_value.install.return_value = False
        self.harness.begin()
        self.harness.charm.validate_exporter_configs = mock.Mock()
        self.harness.charm.validate_exporter_configs.return_value = (False, "error")
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("error"))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    @mock.patch("charm.HWToolHelper", return_value=mock.MagicMock())
    def test_07_update_status_all_green(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status when everything is okay."""
        self.mock_bmc_hw_verifier.return_value = [HWTool.IPMI]
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
    def test_08_update_status_check_installed_false(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status when hw tool checks failed."""
        self.mock_bmc_hw_verifier.return_value = [HWTool.IPMI]
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
    def test_09_update_status_exporter_crashed(self, mock_hw_tool_helper, mock_exporter):
        """Test update_status."""
        self.mock_bmc_hw_verifier.return_value = [HWTool.IPMI]
        mock_hw_tool_helper.return_value.install.return_value = (True, "")
        mock_hw_tool_helper.return_value.check_installed.return_value = (True, "")
        mock_exporter.return_value.install.return_value = True
        mock_exporter.return_value.check_health.return_value = False
        mock_exporter.return_value.restart.side_effect = Exception()
        rid = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.begin()
        self.harness.charm.on.install.emit()
        self.harness.add_relation_unit(rid, "grafana-agent/0")

        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            ErrorStatus("Exporter crashed unexpectedly, please refer to systemd logs..."),
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_10_config_changed(self, mock_exporter):
        """Test config change event updates the charm's internal store."""
        self.harness.begin()
        self.harness.charm._stored.installed = True

        new_config = {"exporter-port": 80, "exporter-log-level": "DEBUG"}
        self.harness.update_config(new_config)
        self.harness.charm.on.config_changed.emit()

        for k, v in self.harness.charm.model.config.items():
            self.assertEqual(self.harness.charm._stored.config.get(k), v)

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Missing relation: [cos-agent]")
        )

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_11_config_changed_before_install_complete(self, mock_exporter):
        """Test: config change event is deferred if charm not installed."""
        self.harness.begin()
        self.harness.charm._stored.installed = False

        self.harness.charm.on.config_changed.emit()
        self.assertEqual(self._get_notice_count("config_changed"), 1)
