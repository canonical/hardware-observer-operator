# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import json
import unittest
from pathlib import Path
from unittest import mock

import ops
import ops.testing
import pytest
from ops.model import ActiveStatus, BlockedStatus
from parameterized import parameterized

import charm
from charm import HardwareObserverCharm
from config import HWTool
from service import (
    HARDWARE_EXPORTER_SETTINGS,
    DCGMExporter,
    ExporterError,
    HardwareExporter,
    SmartCtlExporter,
)


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

        driver_patcher = mock.patch("literals.get_cuda_version_from_driver").start()
        driver_patcher.return_value = 12
        self.addCleanup(driver_patcher.stop)

        driver_patcher_service = mock.patch("service.get_cuda_version_from_driver").start()
        driver_patcher_service.return_value = 12
        self.addCleanup(driver_patcher_service.stop)

    def _get_notice_count(self, hook):
        """Return the notice count for a given charm hook."""
        notice_count = 0
        handle = f"HardwareObserverCharm/on/{hook}"
        for event_path, _, _ in self.harness.charm.framework._storage.notices(None):
            if event_path.startswith(handle):
                notice_count += 1
        return notice_count

    @mock.patch("charm.HardwareObserverCharm._dashboards")
    def test_harness(self, _) -> None:
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
    @mock.patch("charm.HardwareObserverCharm._dashboards")
    @mock.patch("charm.DCGMExporter")
    @mock.patch("charm.SmartCtlExporter")
    @mock.patch("charm.HardwareExporter")
    def test_exporters(
        self,
        _,
        stored_tools,
        expect,
        mock_hw_exporter,
        mock_smart_exporter,
        mock_dcgm_exporter,
        mock_dashboards,
    ):
        with mock.patch(
            "charm.HardwareObserverCharm.stored_tools",
            new_callable=mock.PropertyMock(
                return_value=stored_tools,
            ),
        ):
            self.harness.begin()

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
        ) as mock_exporters, mock.patch(
            "charm.HardwareObserverCharm.stored_tools",
            new_callable=mock.PropertyMock(
                return_value=stored_tools,
            ),
        ):
            self.harness.begin()
            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = hw_tool_helper_install_return
            self.harness.charm._on_update_status = mock.MagicMock()

            for mock_exporter, return_val in zip(
                self.harness.charm.exporters, mock_exporter_install_returns
            ):
                mock_exporter.install.return_value = return_val

            if not all(mock_exporter_install_returns):
                with pytest.raises(ExporterError):
                    if event == "install":
                        self.harness.charm.on.install.emit()
                    else:
                        self.harness.charm.on.upgrade_charm.emit()
            else:
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
        mock_stored_tools = {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.SMARTCTL_EXPORTER}
        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ) as mock_exporters, mock.patch(
            "charm.HardwareObserverCharm.stored_tools",
            new_callable=mock.PropertyMock(
                return_value=mock_stored_tools,
            ),
        ) as mock_stored_tools:
            self.harness.begin()
            self.harness.charm.hw_tool_helper = mock.MagicMock()

            self.harness.charm.on.remove.emit()

        self.harness.charm.hw_tool_helper.remove.assert_called_with(
            self.harness.charm.model.resources, mock_stored_tools
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

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ):
            if cos_agent_related:
                self.harness.add_relation("cos-agent", "opentelemetry-collector")
            self.harness.begin()

            self.harness.charm.model.unit.status = BlockedStatus("Random status")
            self.harness.charm._stored.resource_installed = resource_installed
            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.check_installed.return_value = (
                hw_tool_check_installed
            )

            if not all(mock_exporter_healths):
                with pytest.raises(RuntimeError, match=r"^Exporter unhealthy: .*"):
                    self.harness.charm.on.update_status.emit()
                return
            else:
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
            self.harness.charm.stored_tools
        )
        if not hw_tool_check_installed[0]:
            self.assertEqual(
                self.harness.charm.model.unit.status,
                BlockedStatus("hw tools not installed"),
            )
            return

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Unit is ready"))

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
    @mock.patch("charm.HardwareObserverCharm._dashboards")
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
        _,
    ) -> None:
        """Test action detect-hardware."""
        mock_detect_available_tools.return_value = detected_available_tools
        self.harness.begin()
        self.harness.charm._on_install_or_upgrade = mock.MagicMock()
        self.harness.charm.stored_tools = stored_tools

        output = self.harness.run_action("redetect-hardware", {"apply": apply})

        self.assertEqual(output, expect_output)

        if not stored_tools == detected_available_tools:
            if apply:
                self.assertEqual(
                    self.harness.charm.stored_tools,
                    detected_available_tools,
                )
                self.harness.charm._on_install_or_upgrade.assert_called()
            else:
                self.harness.charm._on_install_or_upgrade.assert_not_called()
                self.assertEqual(
                    self.harness.charm.stored_tools,
                    {tool.value for tool in stored_tools},
                )
        else:
            self.harness.charm._on_install_or_upgrade.assert_not_called()

    @parameterized.expand(
        [
            (
                "happy case",
                True,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "No resource_installed",
                False,
                (True, ""),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "invalid config",
                True,
                (False, "invalid msg"),
                [mock.MagicMock(), mock.MagicMock()],
                [(True, ""), (True, "")],
            ),
            (
                "Exporter configure failed",
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
        mock_stored_tools = {HWTool.IPMI_SENSOR, HWTool.IPMI_SEL, HWTool.IPMI_DCMI}

        with mock.patch(
            "charm.HardwareObserverCharm.exporters",
            new_callable=mock.PropertyMock(
                return_value=mock_exporters,
            ),
        ), mock.patch(
            "charm.HardwareObserverCharm.stored_tools",
            new_callable=mock.PropertyMock(
                return_value=mock_stored_tools,
            ),
        ):
            rid = self.harness.add_relation("cos-agent", "opentelemetry-collector")

            self.harness.begin()

            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = (True, "")
            self.harness.charm.hw_tool_helper.check_installed.return_value = (True, "")

            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "opentelemetry-collector/0")
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
            rid = self.harness.add_relation("cos-agent", "opentelemetry-collector")

            self.harness.begin()

            self.harness.charm.hw_tool_helper = mock.MagicMock()
            self.harness.charm.hw_tool_helper.install.return_value = (True, "")
            self.harness.charm.hw_tool_helper.check_installed.return_value = (True, "")

            mock_stored_tools = mock.MagicMock()
            type(mock_stored_tools).stored_tools = mock.PropertyMock(
                return_value=[
                    HWTool.IPMI_SENSOR,
                    HWTool.IPMI_SEL,
                    HWTool.IPMI_DCMI,
                ]
            )

            self.harness.charm.on.install.emit()
            self.harness.add_relation_unit(rid, "opentelemetry-collector/0")
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

    @mock.patch("charm.HardwareObserverCharm._dashboards")
    def test_stored_tools_remove_legacy_smartctl(self, _):
        self.harness.begin()
        self.harness.charm._stored.stored_tools = {"smartctl"}
        assert self.harness.charm.stored_tools == set()

    @mock.patch("charm.socket.getfqdn", return_value="localhost")
    @mock.patch("service.get_bmc_address")
    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    def test_scrape_config(self, mock_exporters, _, __):
        self.harness.begin()
        config = self.harness.charm.model.config
        hw_exporter = HardwareExporter(Path(), config, set())
        smartctl_exporter = SmartCtlExporter(config)
        labels = {"instance": "localhost"}
        dcgm_exporter = DCGMExporter(self.harness.charm.typed_config)

        mock_exporters.return_value = [hw_exporter, smartctl_exporter, dcgm_exporter]

        assert self.harness.charm._scrape_config() == [
            {
                "metrics_path": "/metrics",
                "static_configs": [
                    {
                        "targets": ["localhost:10200"],
                        "labels": labels,
                    }
                ],
                "scrape_timeout": "10s",
            },
            {
                "metrics_path": "/metrics",
                "static_configs": [
                    {
                        "targets": ["localhost:10201"],
                        "labels": labels,
                    }
                ],
                "scrape_timeout": "10s",
            },
            {
                "metrics_path": "/metrics",
                "static_configs": [
                    {
                        "targets": ["localhost:9400"],
                        "labels": labels,
                    }
                ],
                "scrape_timeout": "10s",
            },
        ]

    @mock.patch("charm.socket.getfqdn", return_value="localhost")
    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    def test_scrape_config_no_specific_hardware(self, mock_exporters, _):
        # simulate a hardware that does not have NVIDIA or tools to install hw exporter
        self.harness.begin()
        config = self.harness.charm.model.config
        smartctl_exporter = SmartCtlExporter(config)

        mock_exporters.return_value = [smartctl_exporter]

        assert self.harness.charm._scrape_config() == [
            {
                "metrics_path": "/metrics",
                "static_configs": [
                    {
                        "targets": ["localhost:10201"],
                        "labels": {"instance": "localhost"},
                    }
                ],
                "scrape_timeout": "10s",
            },
        ]

    @mock.patch("service.get_bmc_address")
    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    def test_dashboards(self, mock_exporters, _):
        self.harness.begin()
        config = self.harness.charm.model.config
        hw_exporter = HardwareExporter(Path(), config, set())
        smartctl_exporter = SmartCtlExporter(config)
        dcgm_exporter = DCGMExporter(self.harness.charm.typed_config)

        mock_exporters.return_value = [hw_exporter, smartctl_exporter, dcgm_exporter]

        assert self.harness.charm._dashboards() == [
            "./src/dashboards_hardware_exporter",
            "./src/dashboards_smart_ctl",
            "./src/dashboards_dcgm",
        ]

    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    def test_dashboards_no_specific_hardware(
        self,
        mock_exporters,
    ):
        # simulate a hardware that does not have NVIDIA or tools to install hw exporter
        self.harness.begin()
        config = self.harness.charm.model.config
        smartctl_exporter = SmartCtlExporter(config)

        mock_exporters.return_value = [smartctl_exporter]

        assert self.harness.charm._dashboards() == ["./src/dashboards_smart_ctl"]

    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    @mock.patch.object(HardwareObserverCharm, "stored_tools", new_callable=mock.PropertyMock)
    @mock.patch("src.charm.shutil.copy")
    def test_enable_redfish_alert_rules(self, mock_copy, mock_stored_tools, mock_exporters):
        mock_stored_tools.return_value = {HWTool.REDFISH}

        self.harness.begin()
        self.harness.update_config({"redfish-disable": False})

        self.harness.charm._set_prometheus_alert_rules()

        mock_copy.assert_called_once_with(charm.PROM_RULES_REDFISH, charm.PROM_RULES)

    @mock.patch("charm.HardwareObserverCharm.exporters", new_callable=mock.PropertyMock)
    @mock.patch.object(HardwareObserverCharm, "stored_tools", new_callable=mock.PropertyMock)
    @mock.patch("pathlib.Path.unlink")
    def test_disable_redfish_alert_rules(self, mock_unlink, mock_stored_tools, mock_exporters):
        # Case: REDFISH disabled in config
        mock_stored_tools.return_value = {HWTool.REDFISH}

        self.harness.begin()
        self.harness.update_config({"redfish-disable": True})

        self.harness.charm._set_prometheus_alert_rules()

        mock_unlink.assert_called_with(missing_ok=True)

    @mock.patch("service.get_bmc_address")
    def test_block_wrong_dcgm_config(self, _):
        self.harness.update_config({"dcgm-snap-channel": "wrong-format"})
        self.harness.begin()
        self.assertTrue(isinstance(self.harness.charm.model.unit.status, ops.BlockedStatus))
        self.assertIn("Channel must be in the form", self.harness.charm.model.unit.status.message)
