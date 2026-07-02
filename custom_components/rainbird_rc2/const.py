"""Constants for the Rain Bird RC2 integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "rainbird_rc2"

# CONF_SATELLITE_ID is retained for compatibility with entries created by
# earlier cloud-assisted versions. It now acts only as a stable controller ID.
CONF_SATELLITE_ID: Final = "satellite_id"
CONF_CONTROLLER_TYPE: Final = "controller_type"
CONF_DEFAULT_DURATION: Final = "default_duration"
CONF_LOCAL_HOST: Final = "local_host"
CONF_LOCAL_PASSWORD: Final = "local_password"
CONF_LOCAL_VERIFY_SSL: Final = "local_verify_ssl"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_DURATION: Final = 10
DEFAULT_NAME: Final = "Rain Bird RC2"

STATUS_IDLE: Final = "-"
STATUS_RUNNING: Final = "R"
