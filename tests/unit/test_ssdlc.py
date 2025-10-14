# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for SSDLC logging functionality."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from parameterized import parameterized

from ssdlc import EXPORTER_NAME_TO_SERVICE, Service, SSDLCSysEvent, log_ssdlc_system_event


class TestSSDLCLogging(unittest.TestCase):
    """Test SSDLC logging functions."""

    @mock.patch("ssdlc.logger")
    @mock.patch("ssdlc.datetime")
    def test_log_ssdlc_system_event_with_exporter_name(self, mock_datetime, mock_logger):
        """Test logging with exporter_name string."""
        # Setup mock datetime
        mock_now = mock.MagicMock()
        mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
        mock_datetime.now.return_value.astimezone.return_value = mock_now

        # Call the function with exporter name
        log_ssdlc_system_event(SSDLCSysEvent.STARTUP, "hardware-exporter")

        # Verify logger was called correctly
        mock_logger.warning.assert_called_once()
        logged_data = mock_logger.warning.call_args[0][0]

        self.assertEqual(logged_data["datetime"], "2025-01-01T12:00:00+00:00")
        self.assertEqual(logged_data["appid"], "service.hardware-exporter")
        self.assertEqual(logged_data["event"], "sys_startup:hardware-exporter")
        self.assertEqual(logged_data["level"], "WARN")
        self.assertIn("hardware observer start service", logged_data["description"])

    @mock.patch("ssdlc.logger")
    @mock.patch("ssdlc.datetime")
    def test_log_ssdlc_system_event_with_different_exporter(self, mock_datetime, mock_logger):
        """Test logging with different exporter name."""
        # Setup mock datetime
        mock_now = mock.MagicMock()
        mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
        mock_datetime.now.return_value.astimezone.return_value = mock_now

        # Call the function with dcgm exporter name
        log_ssdlc_system_event(SSDLCSysEvent.SHUTDOWN, "dcgm")

        # Verify logger was called correctly
        mock_logger.warning.assert_called_once()
        logged_data = mock_logger.warning.call_args[0][0]

        self.assertEqual(logged_data["datetime"], "2025-01-01T12:00:00+00:00")
        self.assertEqual(logged_data["appid"], "service.dcgm")
        self.assertEqual(logged_data["event"], "sys_shutdown:dcgm")
        self.assertEqual(logged_data["level"], "WARN")
        self.assertIn("hardware observer shutdown service", logged_data["description"])

    @mock.patch("ssdlc.logger")
    def test_log_ssdlc_system_event_with_unknown_service(self, mock_logger):
        """Test logging with unknown service name."""
        # Call the function with unknown service
        log_ssdlc_system_event(SSDLCSysEvent.STARTUP, "unknown-service")

        # Verify warning was logged with format string and args
        mock_logger.warning.assert_called_once_with(
            "Unknown service name: %s, skipping SSDLC logging", "unknown-service"
        )

    @parameterized.expand(
        [
            (SSDLCSysEvent.STARTUP, "hardware-exporter", ""),
            (SSDLCSysEvent.SHUTDOWN, "dcgm", ""),
            (SSDLCSysEvent.RESTART, "smartctl-exporter", ""),
            (
                SSDLCSysEvent.CRASH,
                "hardware-exporter",
                "Connection timeout",
            ),
        ]
    )
    @mock.patch("ssdlc.logger")
    @mock.patch("ssdlc.datetime")
    def test_log_ssdlc_system_event_all_events(
        self, event, service_name, msg, mock_datetime, mock_logger
    ):
        """Test logging all event types."""
        # Setup mock datetime
        mock_now = mock.MagicMock()
        mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
        mock_datetime.now.return_value.astimezone.return_value = mock_now

        # Call the function
        log_ssdlc_system_event(event, service_name, msg)

        # Verify logger was called
        mock_logger.warning.assert_called_once()
        logged_data = mock_logger.warning.call_args[0][0]

        self.assertEqual(logged_data["datetime"], "2025-01-01T12:00:00+00:00")
        self.assertEqual(logged_data["appid"], f"service.{service_name}")
        self.assertEqual(logged_data["event"], f"{event.value}:{service_name}")
        self.assertEqual(logged_data["level"], "WARN")
        self.assertIsInstance(logged_data["description"], str)
        if msg:
            self.assertIn(msg, logged_data["description"])

    def test_exporter_name_to_service_mapping(self):
        """Test that all exporters are mapped correctly."""
        self.assertEqual(
            EXPORTER_NAME_TO_SERVICE["hardware-exporter"],
            Service.HARDWARE_EXPORTER,
        )
        self.assertEqual(
            EXPORTER_NAME_TO_SERVICE["dcgm"],
            Service.DCGM_EXPORTER,
        )
        self.assertEqual(
            EXPORTER_NAME_TO_SERVICE["smartctl-exporter"],
            Service.SMARTCTL_EXPORTER,
        )

    @mock.patch("ssdlc.logger")
    @mock.patch("ssdlc.datetime")
    def test_log_ssdlc_system_event_with_additional_message(self, mock_datetime, mock_logger):
        """Test logging with additional message."""
        # Setup mock datetime
        mock_now = mock.MagicMock()
        mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
        mock_datetime.now.return_value.astimezone.return_value = mock_now

        # Call with additional message
        additional_msg = "Service failed due to network error"
        log_ssdlc_system_event(SSDLCSysEvent.CRASH, "hardware-exporter", additional_msg)

        # Verify the additional message is included
        logged_data = mock_logger.warning.call_args[0][0]
        self.assertIn(additional_msg, logged_data["description"])

    @mock.patch("ssdlc.logger")
    @mock.patch("ssdlc.datetime")
    def test_log_ssdlc_system_event_datetime_format(self, mock_datetime, mock_logger):
        """Test that datetime is in ISO 8601 format with timezone."""
        # Use a real datetime to test formatting
        test_time = datetime(2025, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
        mock_datetime.now.return_value.astimezone.return_value = test_time

        log_ssdlc_system_event(SSDLCSysEvent.STARTUP, "hardware-exporter")

        logged_data = mock_logger.warning.call_args[0][0]
        # Verify ISO 8601 format with timezone
        self.assertRegex(
            logged_data["datetime"],
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}",
        )


if __name__ == "__main__":
    unittest.main()
