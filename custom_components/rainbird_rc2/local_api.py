"""Local LAN client for Rain Bird RC2/LNK controllers."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse
import warnings

from pyrainbird import rainbird
from pyrainbird.encryption import PayloadCoder
from pyrainbird.resources import LENGTH, RAINBIRD_COMMANDS, RESPONSE
import requests
import urllib3

from .exceptions import RainBirdAuthError, RainBirdConnectionError

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = (15, 15)
_REQUEST_ATTEMPTS = 3
_RETRY_DELAY = 2

HEADERS = {
    "Accept-Language": "en",
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "RainBird/2.0 CFNetwork/811.5.4 Darwin/16.7.0",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Content-Type": "application/octet-stream",
}


def _normalize_url(host: str) -> str:
    """Return the /stick endpoint URL for a host or full URL."""
    value = host.strip().rstrip("/")
    if not value:
        raise RainBirdConnectionError("Local RC2 host is empty")
    if value.startswith(("http://", "https://")):
        return value if value.endswith("/stick") else f"{value}/stick"
    return f"https://{value}/stick"


class RainBirdLocalAPI:
    """Synchronous local Rain Bird API client. Calls must run in an HA executor."""

    def __init__(
        self,
        host: str,
        password: str,
        *,
        verify_ssl: bool = False,
    ) -> None:
        self._url = _normalize_url(host)
        self._password = password
        self._verify_ssl = verify_ssl
        self._coder = PayloadCoder(password, _LOGGER)
        self._session = self._new_session()
        self._request_lock = threading.Lock()
        if not verify_ssl:
            # Silence the expected self-signed certificate warning only for this
            # controller, not for every HTTPS client in the Home Assistant process.
            host_name = urlparse(self._url).hostname or ""
            warnings.filterwarnings(
                "ignore",
                message=(
                    "Unverified HTTPS request is being made to host "
                    f"'{re.escape(host_name)}'"
                ),
                category=urllib3.exceptions.InsecureRequestWarning,
            )

    @staticmethod
    def _new_session() -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        return session

    def _reset_session(self) -> None:
        self._session.close()
        self._session = self._new_session()

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    @property
    def endpoint(self) -> str:
        """Return the configured endpoint, without credentials."""
        return self._url

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict:
        payload = self._coder.encode_command(method, params or {})
        with self._request_lock:
            last_error: Exception | None = None
            for attempt in range(1, _REQUEST_ATTEMPTS + 1):
                try:
                    response = self._session.post(
                        self._url,
                        data=payload,
                        headers=HEADERS,
                        timeout=_TIMEOUT,
                        verify=self._verify_ssl,
                    )
                    body = response.text.strip()
                    if response.status_code in (403, 430):
                        raise RainBirdAuthError(
                            "Local RC2 rejected authentication: "
                            f"{body or response.status_code}"
                        )
                    response.raise_for_status()
                    return self._coder.decode_command(response.content)
                except RainBirdAuthError:
                    raise
                except Exception as err:
                    last_error = err
                    self._reset_session()
                    if attempt < _REQUEST_ATTEMPTS:
                        time.sleep(_RETRY_DELAY * attempt)

            raise RainBirdConnectionError(
                f"Local RC2 request failed for {method} after retries"
            ) from last_error

    def _tunnel_sip(self, command: str, *args: Any) -> dict[str, Any]:
        command_data = RAINBIRD_COMMANDS[command]
        data = rainbird.encode(command, *args)
        response = self._request(
            "tunnelSip",
            {"data": data, "length": command_data[LENGTH]},
        )
        if "data" not in response:
            raise RainBirdConnectionError("Local RC2 reply missing tunnelSip data")
        decoded = rainbird.decode(response["data"])
        expected = command_data[RESPONSE]
        if response["data"][:2] != expected:
            raise RainBirdConnectionError(
                f"Local RC2 returned unexpected response for {command}"
            )
        return decoded

    def get_serial_number(self) -> str:
        """Return the local controller serial number."""
        response = self._tunnel_sip("SerialNumberRequest")
        return str(response.get("serialNumber", ""))

    def get_active_zones(self) -> set[int]:
        """Return active terminal numbers reported by the local controller."""
        response = self._tunnel_sip("CurrentStationsActiveRequest", 0)
        active = int(response.get("activeStations", 0))
        length = RAINBIRD_COMMANDS["CurrentStationsActiveResponse"]["activeStations"][
            LENGTH
        ]
        mask = f"{active:0{length}X}"
        active_zones: set[int] = set()
        rest = mask
        index = 1
        while rest:
            current = int(rest[:2], 16)
            rest = rest[2:]
            for bit in range(8):
                if current & (1 << bit):
                    active_zones.add(index)
                index += 1
        return active_zones

    def get_available_zones(self) -> set[int]:
        """Return terminal numbers available on the local controller."""
        response = self._tunnel_sip("AvailableStationsRequest", 0)
        available = int(response.get("setStations", 0))
        length = RAINBIRD_COMMANDS["AvailableStationsResponse"]["setStations"][LENGTH]
        mask = f"{available:0{length}X}"
        available_zones: set[int] = set()
        rest = mask
        index = 1
        while rest:
            current = int(rest[:2], 16)
            rest = rest[2:]
            for bit in range(8):
                if current & (1 << bit):
                    available_zones.add(index)
                index += 1
        return available_zones

    def irrigate_zone(self, zone: int, minutes: int) -> None:
        """Start one terminal for the requested number of minutes."""
        self._tunnel_sip("ManuallyRunStationRequest", zone, minutes)

    def stop_irrigation(self) -> None:
        """Stop all local irrigation."""
        self._tunnel_sip("StopIrrigationRequest")
