# Copyright 2023 jneo8
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest import mock

import ops
import ops.testing
from ops.model import ActiveStatus

from charm import PrometheusHardwareExporterCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(PrometheusHardwareExporterCharm)
        self.addCleanup(self.harness.cleanup)

    @classmethod
    def setUpClass(cls):
        pass

    def _get_notice_count(self, hook):
        """Return the notice count for a given charm hook."""
        notice_count = 0
        handle = f"PrometheusHardwareExporterCharm/on/{hook}"
        for event_path, _, _ in self.harness.charm.framework._storage.notices(None):
            if event_path.startswith(handle):
                notice_count += 1
        return notice_count

    def test_01_harness(self) -> None:
        """Test charm initialise."""
        self.harness.begin()
        self.assertFalse(self.harness.charm._stored.installed)
        self.assertTrue(isinstance(self.harness.charm._stored.config, ops.framework.StoredDict))

    @mock.patch("charm.VendorHelper", return_value=mock.MagicMock())
    def test_02_install(self, mock_vendor_helper) -> None:
        """Test event install."""
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        print(self.harness.charm.vendor_helper.install)
        self.harness.charm.vendor_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

    @mock.patch("charm.VendorHelper", return_value=mock.MagicMock())
    def test_03_upgrade_charm(self, mock_vendor_helper) -> None:
        """Test event upgrade_charm."""
        self.harness.begin()
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.installed)

        print(self.harness.charm.vendor_helper.install)
        self.harness.charm.vendor_helper.install.assert_called_with(
            self.harness.charm.model.resources
        )

        self.harness.charm.unit.status = ActiveStatus("Install complete")

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_04_config_changed(self, mock_exporter):
        self.harness.begin()
        default_dict = {"exporter-channel": "latest/edge", "fake-config": "fake-value"}

        self.harness.charm._stored.config = default_dict
        self.harness.charm._stored.installed = True

        self.harness.charm.on.config_changed.emit()

        for k, v in self.harness.charm.model.config.items():
            self.assertTrue(self.harness.charm._stored.config.get(k) == v)

        self.assertTrue(self.harness.charm._stored.config["exporter-snap"] is None)

        self.assertTrue(self.harness.charm._stored.config["fake-config"] == "fake-value")
        self.harness.charm.exporter.on_config_changed.assert_called_with(
            set({"exporter-snap", "exporter-channel"})
        )

        self.assertTrue(self.harness.charm.unit.status == ActiveStatus("Unit is ready"))

    @mock.patch("charm.Exporter", return_value=mock.MagicMock())
    def test_05_config_changed_before_install_complete(self, mock_exporter):
        """Test: config change event is defered if charm not installed."""
        self.harness.begin()
        self.harness.charm._stored.installed = False

        self.harness.charm.on.config_changed.emit()
        self.assertEqual(self._get_notice_count("config_changed"), 1)

    @mock.patch("charm.os.path.getsize", return_value=1)
    def test_06_snap_path_resource_provided(self, mock_getsize):
        """snap_path is set up correctly if resource is provided."""
        self.harness.begin()
        self.harness.add_resource("exporter-snap", "exporter-snap-contont")
        self.harness.charm.snap_path
        self.assertTrue(self.harness.charm._snap_path_set)
        self.assertTrue(self.harness.charm._snap_path is not None)

    @mock.patch("charm.os.path.getsize", return_value=0)
    def test_07_snap_path_resource_provided(self, mock_getsize):
        """snap_path is set to None if resource size if zero."""
        self.harness.begin()
        self.harness.add_resource("exporter-snap", "exporter-snap-contont")
        self.harness.charm.snap_path
        self.assertTrue(self.harness.charm._snap_path_set)
        self.assertTrue(self.harness.charm._snap_path is None)

    def test_08_snap_path_resource_missing(self):
        """snap_path is set up correctly if resource is not provided."""
        self.harness.begin()
        self.harness.charm.snap_path
        self.assertTrue(self.harness.charm._snap_path_set)
        self.assertTrue(self.harness.charm._snap_path is None)
