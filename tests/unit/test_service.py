# Copyright 2024 Canotical Ltd.
# See LICENSE file for licensing details.

import pathlib
import tempfile
import unittest
from unittest import mock

import yaml
from parameterized import parameterized
from redfish.rest.v1 import InvalidCredentialsError

import service
from config import HARDWARE_EXPORTER_SETTINGS, HWTool


class TestBaseExporter(unittest.TestCase):
    """Test Hardware Exporter methods."""

    def setUp(self) -> None:
        """Set up harness for each test case."""
        systemd_lib_patcher = mock.patch.object(service, "systemd")
        self.mock_systemd = systemd_lib_patcher.start()
        self.addCleanup(systemd_lib_patcher.stop)

        get_bmc_address_patcher = mock.patch("service.get_bmc_address", return_value="127.0.0.1")
        get_bmc_address_patcher.start()
        self.addCleanup(get_bmc_address_patcher.stop)

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
        )

    @parameterized.expand(
        [
            (
                {
                    "verify_render_files_exist": True,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": True,
                },
                {
                    "verify_render_files_exist": True,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": True,
                },
                True,
                True,
            ),
            (
                {
                    "verify_render_files_exist": True,
                    "install_resources": False,
                    "render_config": True,
                    "render_service": True,
                },
                {
                    "verify_render_files_exist": False,
                    "install_resources": True,
                    "render_config": False,
                    "render_service": False,
                },
                False,
                False,
            ),
            (
                {
                    "verify_render_files_exist": True,
                    "install_resources": True,
                    "render_config": False,
                    "render_service": True,
                },
                {
                    "verify_render_files_exist": False,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": False,
                },
                False,
                False,
            ),
            (
                {
                    "verify_render_files_exist": True,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": False,
                },
                {
                    "verify_render_files_exist": False,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": True,
                },
                False,
                False,
            ),
            (
                {
                    "verify_render_files_exist": False,
                    "install_resources": True,
                    "resources_exist": True,
                    "render_config": True,
                    "render_service": True,
                },
                {
                    "verify_render_files_exist": True,
                    "verify_render_files_exist": True,
                    "install_resources": True,
                    "render_config": True,
                    "render_service": True,
                },
                False,
                False,
            ),
        ]
    )
    def test_install(self, mock_methods, method_calls, expected_result, systemd_daemon_called):
        """Test exporter install method."""
        for method, return_value in mock_methods.items():
            m = mock.MagicMock()
            m.return_value = return_value
            setattr(self.exporter, method, m)

        result = self.exporter.install()
        self.assertEqual(result, expected_result)

        for method, accept_called in method_calls.items():
            m = getattr(self.exporter, method)
            if accept_called:
                m.assert_called()
            else:
                m.assert_not_called()

        if systemd_daemon_called:
            self.mock_systemd.daemon_reload.assert_called_once()
        else:
            self.mock_systemd.daemon_reload.assert_not_called()

    def test_install_failed_resources_not_exist(self):
        """Test exporter install method when rendering fails."""
        self.exporter.install_resources = mock.MagicMock()
        self.exporter.install_resources.return_value = True
        self.exporter.resources_exist = mock.MagicMock()
        self.exporter.resources_exist.return_value = False
        self.exporter.render_config = mock.MagicMock()
        self.exporter.render_config.return_value = True
        self.exporter.render_service = mock.MagicMock()
        self.exporter.render_service.return_value = True

        result = self.exporter.install()
        self.assertFalse(result)

        self.exporter.install_resources.assert_called()
        self.exporter.resources_exist.assert_called()
        self.exporter.render_config.assert_not_called()
        self.exporter.render_service.assert_not_called()

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

    def test_validate_exporter_config_okay(self):
        self.exporter.port = 10000
        self.exporter.log_level = "debug"
        self.assertEqual(
            (True, "Exporter config is valid."), self.exporter.validate_exporter_configs()
        )

    def test_validate_exporter_config_failed_port(self):
        self.exporter.port = 70000
        self.assertEqual(
            (False, "Invalid config: exporter's port"),
            self.exporter.validate_exporter_configs(),
        )

    def test_validate_exporter_config_failed_log_level(self):
        self.exporter.port = 10000
        self.exporter.log_level = "not-allowed_level_choices"
        self.assertEqual(
            (False, "Invalid config: 'exporter-log-level'"),
            self.exporter.validate_exporter_configs(),
        )

    @mock.patch("service.remove_file")
    def test_remove_service_okay(self, mock_remove_file):
        self.exporter.exporter_service_path = mock.MagicMock()
        self.exporter.exporter_service_path.exists.return_value = True
        mock_remove_file.return_value = "rm-something"
        result = self.exporter.remove_service()
        self.assertEqual(result, "rm-something")
        mock_remove_file.assert_called_with(self.exporter.exporter_service_path)

    @mock.patch("service.remove_file")
    def test_remove_service_file_not_exists(self, mock_remove_file):
        self.exporter.exporter_service_path = mock.MagicMock()
        self.exporter.exporter_service_path.exists.return_value = False
        result = self.exporter.remove_service()
        self.assertTrue(result)
        mock_remove_file.assert_not_called()

    @mock.patch("service.remove_file")
    def test_remove_config_okay(self, mock_remove_file):
        self.exporter.exporter_config_path = mock.MagicMock()
        self.exporter.exporter_config_path.exists.return_value = True
        mock_remove_file.return_value = "rm-something"
        result = self.exporter.remove_config()
        self.assertEqual(result, "rm-something")
        mock_remove_file.assert_called_with(self.exporter.exporter_config_path)

    @mock.patch("service.remove_file")
    def test_remove_config_file_not_exists(self, mock_remove_file):
        self.exporter.exporter_config_path = mock.MagicMock()
        self.exporter.exporter_config_path.exists.return_value = False
        result = self.exporter.remove_config()
        self.assertTrue(result)
        mock_remove_file.assert_not_called()

    @mock.patch("service.remove_file")
    def test_remove_config_skip(self, mock_remove_file):
        result = self.exporter.remove_config()
        self.assertTrue(result)
        mock_remove_file.assert_not_called()

    def test_install_resources(self):
        result = self.exporter.install_resources()
        self.assertTrue(result)

    def test_remove_resources(self):
        result = self.exporter.remove_resources()
        self.assertTrue(result)

    def test_resource_exists(self):
        result = self.exporter.resources_exist()
        self.assertTrue(result)

    @mock.patch("service.systemd")
    def test__restart(self, mock_systemd):
        self.exporter._restart()
        mock_systemd.service_restart.assert_called_with(self.exporter.exporter_name)

    @mock.patch("service.systemd")
    def test_check_health_okay(self, mock_systemd):
        mock_systemd.service_failed.return_value = True
        self.assertFalse(self.exporter.check_health())

    @mock.patch("service.systemd")
    def test_check_health_failed(self, mock_systemd):
        mock_systemd.service_failed.return_value = False
        self.assertTrue(self.exporter.check_health())

    @mock.patch("service.systemd")
    def test_check_active(self, mock_systemd):
        mock_systemd.service_running.return_value = True
        self.assertTrue(self.exporter.check_active())

    @mock.patch("service.systemd")
    def test_check_active_failed(self, mock_systemd):
        mock_systemd.service_running.return_value = False
        self.assertFalse(self.exporter.check_active())

    def test_render_service(self):
        self.exporter._render_service = mock.MagicMock()
        self.exporter._render_service.return_value = "some-bool"
        result = self.exporter.render_service()
        self.exporter._render_service.assert_called_with({})
        self.assertEqual(result, "some-bool")

    @mock.patch("service.write_to_file")
    def test__render_service(self, mock_write_to_file):
        self.exporter.service_template.render = mock.MagicMock()
        self.exporter.exporter_service_path = "some-config-path"
        self.exporter.service_template.render.return_value = "some-content"
        mock_write_to_file.return_value = "some-result"

        params = {"A": "a", "B": "b"}
        result = self.exporter._render_service(params)
        self.assertEqual(mock_write_to_file.return_value, result)

        self.exporter.service_template.render.assert_called_with(**params)
        mock_write_to_file.assert_called_with("some-config-path", "some-content")

    @mock.patch("service.write_to_file")
    def test_render_config_okay(self, mock_write_to_file):
        self.exporter.exporter_config_path = "some-path"
        self.exporter._render_config_content = mock.MagicMock()
        self.exporter._render_config_content.return_value = "some-config-content"
        mock_write_to_file.return_value = "some-result"

        result = self.exporter.render_config()

        mock_write_to_file.assert_called_with("some-path", "some-config-content", mode=0o600)
        self.assertEqual("some-result", result)

    @mock.patch("service.write_to_file")
    def test_render_config_skip(self, mock_write_to_file):
        self.exporter.exporter_config_path = None
        mock_write_to_file.return_value = "some-result"

        result = self.exporter.render_config()

        mock_write_to_file.assert_not_called()
        self.assertEqual(True, result)

    def test__render_config_content(self):
        result = self.exporter._render_config_content()
        self.assertEqual(result, "")

    @parameterized.expand(
        [
            (True, True, True, True),
            (True, False, True, False),
            (True, True, False, False),
            (False, True, True, True),
        ]
    )
    def test_verify_render_files_exist(
        self, required_config, config_exists, service_exists, expect
    ):
        self.exporter.exporter_config_path = None
        if required_config:
            self.exporter.exporter_config_path = mock.MagicMock()
            self.exporter.exporter_config_path.exists.return_value = config_exists
        self.exporter.exporter_service_path = mock.MagicMock()
        self.exporter.exporter_service_path.exists.return_value = service_exists

        result = self.exporter.verify_render_files_exist()
        self.assertEqual(result, expect)

    @parameterized.expand(
        [
            ("success", [False, False, True, True]),
            ("failure", [False, False, False, False]),
            ("exception", [Exception("Some error"), Exception("Some error")]),
        ]
    )
    @mock.patch("service.sleep")
    def test_restart(self, _, check_active_results, mock_sleep):
        # Mocking necessary methods and attributes
        self.exporter.settings.health_retry_count = 3
        self.exporter.settings.health_retry_timeout = 1
        self.exporter._restart = mock.MagicMock()
        self.exporter.check_active = mock.MagicMock()
        self.exporter.check_active.side_effect = check_active_results

        # Call the restart method
        if isinstance(check_active_results[-1], Exception) or check_active_results[-1] is False:
            with self.assertRaises(service.ExporterError):
                self.exporter.restart()
        else:
            self.exporter.restart()

        # Assert that the methods are called as expected
        if isinstance(check_active_results[-1], Exception):
            pass  # If an exception occurs, it's caught and raised
        else:
            self.assertTrue(self.exporter.check_active.called)


class TestHardwareExporter(unittest.TestCase):
    """Test Hardware Exporter's methods."""

    def setUp(self) -> None:
        """Set up harness for each test case."""
        get_bmc_address_patcher = mock.patch("service.get_bmc_address", return_value="127.0.0.1")
        get_bmc_address_patcher.start()
        self.addCleanup(get_bmc_address_patcher.stop)

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

    def test_render_service(self):
        """Test render service."""
        self.exporter._render_service = mock.MagicMock()
        self.exporter._render_service.return_value = "some result"

        result = self.exporter.render_service()
        self.assertEqual(result, "some result")

        self.exporter._render_service.assert_called_with(
            {
                "CHARMDIR": str(self.exporter.charm_dir),
                "CONFIG_FILE": str(self.exporter.exporter_config_path),
            }
        )

    def test_validate_exporter_config_okay(self):
        self.exporter.redfish_conn_params_valid = mock.MagicMock()
        self.exporter.redfish_conn_params_valid.return_value = True

        self.assertEqual(
            (True, "Exporter config is valid."), self.exporter.validate_exporter_configs()
        )

    @mock.patch("builtins.super", return_value=mock.MagicMock())
    def test_validate_exporter_config_super_failed(self, mock_super):
        self.exporter.redfish_conn_params_valid = mock.MagicMock()
        self.exporter.redfish_conn_params_valid.return_value = True

        mock_super.return_value.validate_exporter_configs.return_value = (False, "something wrong")
        self.assertEqual((False, "something wrong"), self.exporter.validate_exporter_configs())

        mock_super.return_value.validate_exporter_configs.accept_called()
        self.exporter.redfish_conn_params_valid.assert_not_called()

    def test_validate_exporter_config_redfish_conn_params_failed(self):
        self.exporter.redfish_conn_params_valid = mock.MagicMock()
        self.exporter.redfish_conn_params_valid.return_value = False

        self.assertEqual(
            (False, "Invalid config: 'redfish-username' or 'redfish-password'"),
            self.exporter.validate_exporter_configs(),
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

    @mock.patch("service.redfish_client")
    def test_redfish_conn_params_valid_success(self, mock_redfish_client):
        redfish_conn_params = {
            "host": "hosta",
            "username": "usernameb",
            "password": "passwordc",
            "timeout": "timeoutd",
        }
        result = self.exporter.redfish_conn_params_valid(redfish_conn_params)
        self.assertTrue(result)

        mock_redfish_client.assert_called_with(
            base_url="hosta",
            username="usernameb",
            password="passwordc",
            timeout="timeoutd",
            max_retry=self.exporter.settings.redfish_max_retry,
        )
        mock_redfish_client.return_value.login.assert_called_with(auth="session")
        mock_redfish_client.return_value.logout.assert_called()

    @mock.patch("service.redfish_client")
    def test_redfish_conn_params_valid_miss_redfish_params(self, mock_redfish_client):
        redfish_conn_params = {}
        result = self.exporter.redfish_conn_params_valid(redfish_conn_params)
        self.assertEqual(result, None)

        mock_redfish_client.assert_not_called()

    @mock.patch("service.redfish_client")
    def test_redfish_conn_params_valid_failed_invalid_credentials_error(self, mock_redfish_client):
        redfish_conn_params = {
            "host": "hosta",
            "username": "usernameb",
            "password": "passwordc",
            "timeout": "timeoutd",
        }
        mock_redfish_client.side_effect = InvalidCredentialsError
        result = self.exporter.redfish_conn_params_valid(redfish_conn_params)

        mock_redfish_client.assert_called_with(
            base_url="hosta",
            username="usernameb",
            password="passwordc",
            timeout="timeoutd",
            max_retry=self.exporter.settings.redfish_max_retry,
        )
        self.assertFalse(result)
        mock_redfish_client.return_value.login.assert_not_called()

    @mock.patch("service.redfish_client")
    def test_redfish_conn_params_valid_failed_exception(self, mock_redfish_client):
        redfish_conn_params = {
            "host": "hosta",
            "username": "usernameb",
            "password": "passwordc",
            "timeout": "timeoutd",
        }
        mock_redfish_client.side_effect = Exception
        result = self.exporter.redfish_conn_params_valid(redfish_conn_params)

        mock_redfish_client.assert_called_with(
            base_url="hosta",
            username="usernameb",
            password="passwordc",
            timeout="timeoutd",
            max_retry=self.exporter.settings.redfish_max_retry,
        )
        self.assertFalse(result)
        mock_redfish_client.return_value.login.assert_not_called()

    def test_hw_tools(self):
        self.assertEqual(
            self.exporter.hw_tools(),
            [
                HWTool.STORCLI,
                HWTool.SSACLI,
                HWTool.SAS2IRCU,
                HWTool.SAS3IRCU,
                HWTool.PERCCLI,
                HWTool.IPMI_DCMI,
                HWTool.IPMI_SEL,
                HWTool.IPMI_SENSOR,
                HWTool.REDFISH,
            ],
        )


class TestSmartMetricExporter(unittest.TestCase):
    """Test SmartCtlExporter's methods."""

    def setUp(self) -> None:
        """Set up harness for each test case."""
        search_path = pathlib.Path(f"{__file__}/../../..").resolve()
        self.mock_config = {
            "smartctl-exporter-port": 10201,
            "collect-timeout": 10,
            "exporter-log-level": "INFO",
        }
        self.exporter = service.SmartCtlExporter(search_path, self.mock_config)

    def test_hw_tools(self):
        self.assertEqual(self.exporter.hw_tools(), [HWTool.SMARTCTL])

    @mock.patch("service.systemd", return_value=mock.MagicMock())
    def test_install_resource_restart(self, mock_systemd):
        self.exporter.strategy = mock.MagicMock()
        self.exporter.check_active = mock.MagicMock()
        self.exporter.check_active.return_value = True

        self.exporter.install_resources()

        self.exporter.strategy.install.accept_called()
        self.exporter.check_active.accept_called()
        mock_systemd.service_stop.accept_called_with(self.exporter.exporter_name)
        mock_systemd.service_restart.accept_called_with(self.exporter.exporter_name)

    @mock.patch("service.systemd", return_value=mock.MagicMock())
    def test_install_resource_no_restart(self, mock_systemd):
        self.exporter.strategy = mock.MagicMock()
        self.exporter.check_active = mock.MagicMock()
        self.exporter.check_active.return_value = False

        self.exporter.install_resources()

        self.exporter.strategy.install.accept_called()
        self.exporter.check_active.accept_called()
        mock_systemd.service_stop.accept_not_called()
        mock_systemd.service_restart.accept_not_called()

    def test_resource_exists(self):
        self.exporter.strategy = mock.MagicMock()

        self.exporter.resources_exist()
        self.exporter.strategy.check.accept_called()

    def test_resources_exist(self):
        self.exporter.strategy = mock.MagicMock()
        self.exporter.strategy.check.return_value = "some result"

        result = self.exporter.resources_exist()

        self.assertEqual(result, "some result")
        self.exporter.strategy.check.accept_called()

    def test_resource_remove(self):
        self.exporter.strategy = mock.MagicMock()

        result = self.exporter.remove_resources()
        self.assertEqual(result, True)

        self.exporter.strategy.remove.accept_called()


class TestWriteToFile(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()

    def tearDown(self):
        pathlib.Path(self.temp_file.name).unlink()

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("service.os")
    def test_write_to_file_success(self, mock_os, mock_open):
        path = pathlib.Path(self.temp_file.name)
        content = "Hello, world!"

        mock_file = mock_open.return_value.__enter__.return_value

        result = service.write_to_file(path, content)
        self.assertTrue(result)

        mock_open.assert_called_with(path, "w", encoding="utf-8")
        mock_file.write.assert_called_with(content)

    @mock.patch("service.os.open", new_callable=mock.mock_open)
    @mock.patch("service.os.fdopen", new_callable=mock.mock_open)
    @mock.patch("service.os")
    def test_write_to_file_with_mode_success(self, mock_os, mock_fdopen, mock_open):
        path = pathlib.Path(self.temp_file.name)
        content = "Hello, world!"

        mock_file = mock_fdopen.return_value.__enter__.return_value

        result = service.write_to_file(path, content, mode=0o600)
        self.assertTrue(result)

        mock_open.assert_called_with(path, mock_os.O_CREAT | mock_os.O_WRONLY, 0o600)
        mock_fdopen.assert_called_with(mock_open.return_value, "w", encoding="utf-8")
        mock_file.write.assert_called_with(content)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_write_to_file_permission_error(self, mock_open):
        path = pathlib.Path(self.temp_file.name)
        content = "Hello, world!"

        # Mocking os.open and os.fdopen to raise PermissionError
        mock_open.side_effect = PermissionError("Permission denied")

        # Call the function
        result = service.write_to_file(path, content)

        # Assert calls and result
        self.assertFalse(result)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_write_to_file_not_a_directory_error(self, mock_open):
        path = pathlib.Path(self.temp_file.name)
        content = "Hello, world!"

        # Mocking os.open and os.fdopen to raise PermissionError
        mock_open.side_effect = NotADirectoryError("Not a directory")

        # Call the function
        result = service.write_to_file(path, content)

        # Assert calls and result
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
