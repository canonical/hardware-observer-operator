#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Helper functions for the charm to manage exporter lifecycle.
from logging import getLogger
from time import sleep
from typing import List

from ops.model import BlockedStatus, MaintenanceStatus

from service import BaseExporter, ExporterError

logger = getLogger(__name__)


def get_exporter(exporter: BaseExporter):
    """Install and get an exporter"""
    installed = exporter.install()
    if not installed:
        logger.error(f"Failed to install {exporter.exporter_name}")
        return

    return exporter


def remove_exporter(exporter: BaseExporter, model):
    """Uninstall an exporter."""
    model.unit.status = MaintenanceStatus(f"Removing {exporter.exporter_name}...")
    exporter.uninstall()
    logger.info(f"Removed {exporter.exporter_name}.")


def get_installed_exporters(all_exporters) -> List:
    """Get a list of installed exporters."""
    installed_exporters = []
    for exporter in all_exporters:
        if exporter.exporter_service_path.exists():
            installed_exporters.append(exporter)

    return installed_exporters


def check_exporter_health(exporter: BaseExporter, model) -> bool:
    """Check exporter health."""
    if not exporter.check_health():
        logger.warning(f"{exporter.exporter_name} - Exporter health check failed.")
        try:
            restart_exporter(
                exporter,
                exporter.settings.health_retry_count,
                exporter.settings.health_retry_timeout,
            )
        except ExporterError as e:
            msg = f"Exporter {exporter.exporter_name} crashed unexpectedly: {e}"
            logger.error(msg)
            # Setting the status as blocked instead of error
            # since other exporters may still be healthy.
            model.unit.status = BlockedStatus(msg)
            return False

    return True


def restart_exporter(exporter, retry_count, retry_timeout):
    """Restart exporter service with retry."""
    logger.info(f"Restarting exporter - {exporter.exporter_name}")
    try:
        for i in range(1, retry_count + 1):
            logger.warning("Restarting exporter - %d retry", i)
            exporter.restart()
            sleep(retry_timeout)
            if exporter.check_active():
                logger.info(f"Exporter - {exporter.exporter_name} active after restart.")
                break
        if not exporter.check_active():
            logger.error(f"Failed to restart exporter - {exporter.exporter_name}.")
            raise ExporterError()
    except Exception as err:  # pylint: disable=W0718
        logger.error(f"Exporter {exporter.exporter_name} crashed unexpectedly: %s", err)
        raise ExporterError() from err


def reconfigure_exporter(exporter: BaseExporter, model) -> bool:
    """Reconfigure an exporter."""
    exporter.set_config(model.config)
    success = exporter.render_config()
    if not success:
        message = f"Failed to configure {exporter.exporter_name}, please check if the server is healthy."
        model.unit.status = BlockedStatus(message)
        return False
    exporter.restart()
    return True
