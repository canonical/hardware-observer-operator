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

import charm
from charm import ExporterError, HardwareObserverCharm
from config import HWTool
from service import HARDWARE_EXPORTER_SETTINGS, DCGMExporter, HardwareExporter, SmartCtlExporter


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(HardwareObserverCharm)
        self.addCleanup(self.harness.cleanup)

        detect_available_tools_patcher = mock.patch.object(charm, "detect_available_tools")
        self.mock_detect_available_tools = detect_available_tools_patcher.start()
        self.mock_detect_available_tools.return_value = {
            HWTool.IPMI_SENSOR,
            HWTool.IPMI_SEL,
            HWTool.IPMI_DCMI,
            HWTool.REDFISH,
        }

        self.addCleanup(detect_available_tools_patcher.stop)

        requests_patcher = mock.patch("hw_tools.requests")
        requests_patcher.start()
        self.addCleanup(requests_patcher.stop)

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

    @parameterized.expand(
        [
            (
                "No exporters enabled",
                set(),
                set(),
            ),
            (
                "Enable one exporter",
                {HWTool.IPMI_SEL},
                {"hardware-exporter"},
            ),
            (
                "Enable two exporters",
                {HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                {"hardware-exporter", "smartctl-exporter"},
            ),
            (
                "Enable all exporters",
                {HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER, HWTool.DCGM},
                {"hardware-exporter", "smartctl-exporter", "dcgm"},
            ),
        ]
    )
    @mock.patch("charm.DCGMExporter")
    @mock.patch("charm.SmartCtlExporter")
    @mock.patch("charm.HardwareExporter")
    def test_exporters(
        self, _, stored_tools, expect, mock_hw_exporter, mock_smart_exporter, mock_dcgm_exporter
    ):
        self.harness.begin()
        self.harness.charm.get_stored_tools = mock.MagicMock()
        self.harness.charm.get_stored_tools.return_value = stored_tools

        hw_exporter = mock.MagicMock()
        hw_exporter.exporter_name = HARDWARE_EXPORTER_SETTINGS.name
        mock_hw_exporter.hw_tools.return_value = HardwareExporter.hw_tools()
        mock_hw_exporter.return_value = hw_exporter

        smart_exporter = mock.MagicMock()
        smart_exporter.exporter_name = SmartCtlExporter.exporter_name
        mock_smart_exporter.hw_tools.return_value = SmartCtlExporter.hw_tools()
        mock_smart_exporter.return_value = smart_exporter

        dcgm_exporter = mock.MagicMock()
        dcgm_exporter.exporter_name = DCGMExporter.exporter_name
        mock_dcgm_exporter.hw_tools.return_value = DCGMExporter.hw_tools()
        mock_dcgm_exporter.return_value = dcgm_exporter

        exporters = self.harness.charm.exporters
        self.harness.charm.get_stored_tools.assert_called()

        self.assertEqual({exporter.exporter_name for exporter in exporters}, expect)

    @parameterized.expand(
        [
            (
                "happy case",
                "install",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [True, True],
            ),
            (
                "happy case",
                "upgrade",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [True, True],
            ),
            (
                "missing resource",
                "install",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (False, "miss something"),
                [mock.MagicMock(), mock.MagicMock()],
                [True, True],
            ),
            (
                "missing resource",
                "upgrade",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (False, "miss something"),
                [mock.MagicMock(), mock.MagicMock()],
                [True, True],
            ),
            (
                "Exporter install fail",
                "install",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [False, True],
            ),
            (
                "Exporter install fail",
                "upgrade",
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [False, True],
            ),
        ]
    )
    def test_install_or_upgrade(
        self,
        _,
        event,
        stored_tools,
        hw_tool_helper_install_return,
        mock_exporters,
        mock_exporter_install_returns,
    ) -> None:
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ) as mock_exporters:
            self.harness.begin()
            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = hw_tool_helper_install_return
            self.harness.charm.get_stored_tools = mock.MagicMock()
            self.harness.charm.get_stored_tools.return_value = stored_tools
            self.harness.charm._on_update_status = mock.MagicMock()

            for mock_exporter, return_val in zip(
                self.harness.charm.exporters, mock_exporter_install_returns
            ):
                mock_exporter.install.return_value = return_val

            if event == "install":
                self.harness.charm.on.install.emit()
            else:
                self.harness.charm.on.upgrade_charm.emit()

        self.harness.charm.hw_tool_helper.install.assert_called_with(
            self.harness.charm.model.resources,
            stored_tools,
        )

        store_resource = False
        if hw_tool_helper_install_return[0]:
            if all(mock_exporter_install_returns):
                for mock_exporter in mock_exporters:
                    mock_exporter.install.assert_called()
                store_resource = True

        self.assertEqual(self.harness.charm._stored.resource_installed, store_resource)
        if store_resource:
            self.harness.charm._on_update_status.assert_called()

    def test_remove(self):
        mock_exporters = {mock.MagicMock(), mock.MagicMock()}
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ) as mock_exporters:
            self.harness.begin()
            self.harness.charm.hw_tool_helper = mock.MagicMock()

            self.harness.charm.get_stored_tools = mock.MagicMock()
            self.harness.charm.get_stored_tools.return_value = {
                HWTool.IPMI_SENSOR,
                HWTool.IPMI_SEL,
                HWTool.SMARTCTL_EXPORTER,
            }

            self.harness.charm.on.remove.emit()

        self.harness.charm.hw_tool_helper.remove.assert_called_with(
            self.harness.charm.model.resources,
            {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER},
        )
        for mock_exporter in mock_exporters:
            mock_exporter.uninstall.assert_called()
        self.assertFalse(self.harness.charm._stored.resource_installed)

    @parameterized.expand(
        [
            (
                "happy case",
                True,
                True,
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
                (True, ""),
                [True, True],
            ),
            (
                "resouce_install not True",
                False,
                True,
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
                (True, ""),
                [True, True],
            ),
            (
                "No cos_agent_related",
                True,
                False,
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
                (True, ""),
                [True, True],
            ),
            (
                "Exporter config invalid",
                True,
                True,
                [mock.MagicMock(), mock.MagicMock()],
                [(False, "Some invalid msg"), (True, "")],
                (True, ""),
                [True, True],
            ),
            (
                "hw tools install not ok",
                True,
                True,
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
                (False, "hw tools not installed"),
                [True, True],
            ),
            (
                "Exporter not health",
                True,
                True,
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
                (True, ""),
                [True, False],
            ),
        ]
    )
    def test_update_status(  # noqa: C901
        self,
        _,
        resource_installed,
        cos_agent_related,
        mock_exporters,
        mock_exporter_validate_exporter_configs_returns,
        hw_tool_check_installed,
        mock_exporter_healths,
    ):
        for mock_exporter, config_valid, health in zip(
            mock_exporters,
            mock_exporter_validate_exporter_configs_returns,
            mock_exporter_healths,
        ):
            mock_exporter.validate_exporter_configs.return_value = config_valid
            mock_exporter.check_health.return_value = health
            mock_exporter.restart.side_effect = ExporterError

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            if cos_agent_related:
                self.harness.add_relation("cos-agent", "grafana-agent")
            self.harness.begin()

            self.harness.charm.model.unit.status = BlockedStatus("Random status")
            self.harness.charm._stored.resource_installed = resource_installed
            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.check_installed.return_value = (
                hw_tool_check_installed
            )

            self.harness.charm.on.update_status.emit()

        if not resource_installed:
            self.assertEqual(
                self.harness.charm.model.unit.status,
                BlockedStatus("Random status"),
            )
            return

        if not cos_agent_related:
            self.assertEqual(
                self.harness.charm.model.unit.status,
                BlockedStatus("Missing relation: [cos-agent]"),
            )
            return

        if not all([res[0] for res in mock_exporter_validate_exporter_configs_returns]):
            for valid_config, mock_exporter in zip(
                mock_exporter_validate_exporter_configs_returns,
                mock_exporters,
            ):
                ok = valid_config[0]
                msg = valid_config[1]
                if ok:
                    mock_exporter.validate_exporter_configs.assert_called()
                else:
                    self.assertEqual(
                        self.harness.charm.model.unit.status,
                        BlockedStatus(msg),
                    )
                    break
            return

        self.harness.charm.hw_tool_helper.check_installed.assert_called_with(
            self.harness.charm.get_stored_tools()
        )
        if not hw_tool_check_installed[0]:
            self.assertEqual(
                self.harness.charm.model.unit.status,
                BlockedStatus("hw tools not installed"),
            )
            return

        if all(mock_exporter_healths):
            self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))
        else:
            for mock_exporter, health in zip(
                mock_exporters,
                mock_exporter_healths,
            ):
                if health:
                    mock_exporter.restart.assert_not_called()
                else:
                    msg = (
                        f"Exporter {mock_exporter.exporter_name} "
                        f"crashed unexpectedly: {ExporterError()}"
                    )
                    self.assertEqual(self.harness.charm.unit.status, BlockedStatus(msg))

    @parameterized.expand(
        [
            (
                False,
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH},
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH},
                ops.testing.ActionOutput(
                    results={
                        "hardware-change-detected": False,
                        "current-hardware-tools": "ipmi_dcmi,ipmi_sel,ipmi_sensor,redfish",
                        "update-hardware-tools": False,
                        "detected-hardware-tools": "",
                    },
                    logs=[],
                ),
            ),
            (
                False,
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH},
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI},
                ops.testing.ActionOutput(
                    results={
                        "hardware-change-detected": True,
                        "detected-hardware-tools": "ipmi_dcmi,ipmi_sel,ipmi_sensor",
                        "current-hardware-tools": "ipmi_dcmi,ipmi_sel,ipmi_sensor,redfish",
                        "update-hardware-tools": False,
                    },
                    logs=[],
                ),
            ),
            (
                True,
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI, HWTool.REDFISH},
                {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI},
                ops.testing.ActionOutput(
                    results={
                        "hardware-change-detected": True,
                        "detected-hardware-tools": "ipmi_dcmi,ipmi_sel,ipmi_sensor",
                        "current-hardware-tools": "ipmi_dcmi,ipmi_sel,ipmi_sensor,redfish",
                        "update-hardware-tools": True,
                    },
                    logs=["Run install hook with enable tools: ipmi_dcmi,ipmi_sel,ipmi_sensor"],
                ),
            ),
            (
                True,
                {HWTool.PERCCLI, HWTool.STORCLI},
                {HWTool.PERCCLI, HWTool.STORCLI},
                ops.testing.ActionOutput(
                    results={
                        "hardware-change-detected": False,
                        "current-hardware-tools": "perccli,storcli",
                        "update-hardware-tools": False,
                        "detected-hardware-tools": "",
                    },
                    logs=[],
                ),
            ),
        ]
    )
    @mock.patch(
        "charm.detect_available_tools",
    )
    def test_detect_hardware_action(
        self,
        apply,
        stored_tools,
        detected_available_tools,
        expect_output,
        mock_detect_available_tools,
    ) -> None:
        """Test action detect-hardware."""
        mock_detect_available_tools.return_value = detected_available_tools
        self.harness.begin()
        self.harness.charm._on_install_or_upgrade = mock.MagicMock()
        self.harness.charm._stored.stored_tools = [tool.value for tool in stored_tools]

        output = self.harness.run_action("redetect-hardware", {"apply": apply})

        self.assertEqual(output, expect_output)

        if not stored_tools == detected_available_tools:
            if apply:
                self.assertEqual(
                    self.harness.charm.get_stored_tools(),
                    detected_available_tools,
                )
                self.harness.charm._on_install_or_upgrade.assert_called()
            else:
                self.harness.charm._on_install_or_upgrade.assert_not_called()
                self.assertEqual(
                    self.harness.charm.get_stored_tools(),
                    {tool.value for tool in stored_tools},
                )
        else:
            self.harness.charm._on_install_or_upgrade.assert_not_called()

    @parameterized.expand(
        [
            (
                "happy case",
                True,
                True,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "No resource_installed",
                False,
                True,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "No cos_agent_related",
                True,
                False,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "invalid config",
                True,
                True,
                (False, "invalid msg"),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "Exporter configure failed",
                True,
                True,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [True, False],
            ),
        ]
    )
    @mock.patch("charm.logger")
    def test_config_changed(
        self,
        _,
        resource_installed,
        cos_agent_related,
        validate_configs_return,
        mock_exporters,
        mock_exporters_configure_returns,
        mock_logger,
    ):
        for mock_exporter, configure_return in zip(
            mock_exporters,
            mock_exporters_configure_returns,
        ):
            mock_exporter.configure.return_value = configure_return

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            if cos_agent_related:
                self.harness.add_relation("cos-agent", "grafana-agent")
            self.harness.begin()
            self.harness.charm._stored.resource_installed = resource_installed
            self.harness.charm.validate_configs = mock.MagicMock()
            self.harness.charm.validate_configs.return_value = validate_configs_return
            self.harness.charm._on_update_status = mock.MagicMock()

            self.harness.charm.on.config_changed.emit()

            if not resource_installed:
                mock_logger.info.assert_called()
                self.harness.charm.validate_configs.assert_not_called()
                self.harness.charm._on_update_status.assert_not_called()
            else:
                if not cos_agent_related:
                    self.harness.charm.validate_configs.assert_not_called()
                    self.harness.charm._on_update_status.assert_called()
                    return
                if not validate_configs_return[0]:
                    self.assertEqual(self.harness.charm.unit.status, BlockedStatus("invalid msg"))
                    self.harness.charm.exporters[0].configure.assert_not_called()
                    return
                if not all(mock_exporters_configure_returns):
                    for mock_exporter, configure_return in zip(
                        mock_exporters,
                        mock_exporters_configure_returns,
                    ):
                        if configure_return:
                            mock_exporter.restart.assert_called()
                        else:
                            message = (
                                f"Failed to configure {mock_exporter.exporter_name}, "
                                f"please check if the server is healthy."
                            )
                            self.assertEqual(
                                self.harness.charm.unit.status, BlockedStatus(message)
                            )
                    self.harness.charm._on_update_status.assert_called()
                self.harness.charm._on_update_status.assert_called()

    def test_config_changed_update_alert_rules(self):
        """Test config changed will update alert rule."""
        mock_exporter = mock.MagicMock()
        mock_exporter.install.return_value = True
        mock_exporter.validate_exporter_configs.return_value = (True, "")
        mock_exporter.check_health.return_value = True
        mock_exporters = [mock_exporter]

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            rid = self.harness.add_relation("cos-agent", "grafana-agent")

            self.harness.begin()

            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = (True, "")
            self.harness.charm.hw_tool_helper.check_installed.return_value = (True, "")

            self.harness.charm.get_stored_tools = mock.MagicMock()
            self.harness.charm.get_stored_tools.return_value = {
                HWTool.IPMI_SENSOR,
                HWTool.IPMI_SEL,
                HWTool.IPMI_DCMI,
            }

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

    def test_upgrade_charm_update_alert_rules(self):
        """Test config changed will update alert rule."""
        mock_exporter = mock.MagicMock()
        mock_exporter.install.return_value = True
        mock_exporter.validate_exporter_configs.return_value = (True, "")
        mock_exporter.check_health.return_value = True
        mock_exporters = [mock_exporter]

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            rid = self.harness.add_relation("cos-agent", "grafana-agent")

            self.harness.begin()

            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = (True, "")
            self.harness.charm.hw_tool_helper.check_installed.return_value = (True, "")

            self.harness.charm.get_stored_tools = mock.MagicMock()
            self.harness.charm.get_stored_tools.return_value = [
                HWTool.IPMI_SENSOR,
                HWTool.IPMI_SEL,
                HWTool.IPMI_DCMI,
            ]

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

    @parameterized.expand(
        [
            ("happy case", True),
            ("No resource_installed", False),
        ]
    )
    def test_on_relation_joined(self, _, resource_installed):
        mock_exporters = [mock.MagicMock()]
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            self.harness.begin()
            self.harness.charm._on_update_status = mock.MagicMock()
            self.harness.charm._stored.resource_installed = resource_installed

            rid = self.harness.add_relation("cos-agent", "grafana-agent")
            self.harness.add_relation_unit(rid, "grafana-agent/0")

        if not resource_installed:
            self.harness.charm._on_update_status.assert_not_called()
            return
        for mock_exporter in mock_exporters:
            mock_exporter.enable_and_start.assert_called()
        self.harness.charm._on_update_status.assert_called()

    @parameterized.expand(
        [
            ("happy case", True),
        ]
    )
    def test_relation_departed(self, _, resource_installed):
        mock_exporters = [mock.MagicMock()]
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            self.harness.begin()
            self.harness.charm._on_update_status = mock.MagicMock()

            rid = self.harness.add_relation("cos-agent", "grafana-agent")
            self.harness.add_relation_unit(rid, "grafana-agent/0")
            rid = self.harness.remove_relation(rid)

        for mock_exporter in mock_exporters:
            mock_exporter.disable_and_stop.assert_called()
        self.harness.charm._on_update_status.assert_called()

    @parameterized.expand(
        [
            (
                "happy case",
                [10000, 10001],
                [(True, ""), (True, "")],
                (True, "Charm config is valid."),
            ),
            (
                "exporter invalied",
                [10000, 10001],
                [(True, ""), (False, "Invalied msg")],
                (False, "Invalied msg"),
            ),
            (
                "happy case",
                [10000, 10000],
                [(True, ""), (True, "")],
                (False, "Ports must be unique for each exporter."),
            ),
        ]
    )
    def test_validate_configs(
        self, _, mock_exporter_ports, mock_exporter_validate_exporter_configs_returns, expect
    ):
        mock_exporters = [mock.MagicMock(), mock.MagicMock()]
        for mock_exporter, port, return_val in zip(
            mock_exporters, mock_exporter_ports, mock_exporter_validate_exporter_configs_returns
        ):
            mock_exporter.validate_exporter_configs.return_value = return_val
            mock_exporter.port = port
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            self.harness.begin()
            result = self.harness.charm.validate_configs()
            self.assertEqual(result, expect)

    def test_get_stored_tools_remove_legacy_smartctl(self):
        self.harness.begin()
        self.harness.charm._stored.stored_tools = {"smartctl"}
        assert self.harness.charm.get_stored_tools() == set()
