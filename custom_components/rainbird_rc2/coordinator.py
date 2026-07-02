"""Local data coordinator for Rain Bird RC2."""

from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, STATUS_IDLE, STATUS_RUNNING
from .exceptions import RainBirdAuthError
from .local_api import RainBirdLocalAPI
from .run_history import RainBirdRunHistory

_LOGGER = logging.getLogger(__name__)


class RainBirdCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the RC2 directly over the local network."""

    def __init__(
        self,
        hass: HomeAssistant,
        local_api: RainBirdLocalAPI,
        controller_id: str,
        controller_name: str,
        scan_interval: int,
        available_zones: set[int],
        run_history: RainBirdRunHistory,
        fallback_stations: list[dict[str, Any]] | None = None,
        serial_number: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_local",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.local_api = local_api
        self.controller_id = controller_id
        # Compatibility with entity unique IDs created by earlier releases.
        self.satellite_id = controller_id
        self.controller_name = controller_name
        self.serial_number = serial_number
        self.available_zones = set(available_zones)
        self.run_history = run_history
        self.fallback_stations = fallback_stations or []
        self._local_last_success: datetime | None = None
        self._local_last_active_zones: set[int] = set()
        self._local_consecutive_errors = 0
        self._local_status_grace = timedelta(seconds=max(90, scan_interval * 4))
        self._expected_terminal: int | None = None
        self._expected_started: datetime | None = None

    def set_expected_run(self, terminal: int, duration_minutes: int) -> None:
        """Publish an acknowledged run while RC2 is temporarily busy."""
        self._expected_terminal = int(terminal)
        self._expected_started = datetime.now()
        self._publish_expected_state(True)

    def clear_expected_run(self) -> None:
        """Publish an acknowledged stop without waiting for a busy RC2."""
        self._expected_terminal = None
        self._expected_started = None
        self._publish_expected_state(False)

    def _publish_expected_state(self, running: bool) -> None:
        if not self.data:
            return
        data = deepcopy(self.data)
        expected_terminal = self._expected_terminal
        for station in data.get("stations", []):
            is_running = bool(
                running
                and expected_terminal is not None
                and int(station.get("terminal", -1)) == expected_terminal
            )
            station["isRunning"] = is_running
            station["status"] = STATUS_RUNNING if is_running else STATUS_IDLE
        data["connection"]["isConnected"] = True
        data["connection"]["connectionSource"] = "LAN"
        data["connection"]["localReachable"] = True
        data["connection"]["localDataStale"] = False
        data["connection"]["localActiveZones"] = (
            [expected_terminal] if running and expected_terminal is not None else []
        )
        self.async_set_updated_data(data)

    def _stations(self, active_zones: set[int]) -> list[dict[str, Any]]:
        fallback_by_terminal = {
            int(station["terminal"]): station
            for station in self.fallback_stations
            if station.get("terminal") is not None
        }
        stations: list[dict[str, Any]] = []
        for terminal in sorted(self.available_zones):
            fallback = fallback_by_terminal.get(terminal, {})
            station_id = int(fallback.get("id", terminal))
            is_running = terminal in active_zones
            history = self.run_history.station(station_id)
            stations.append(
                {
                    "id": station_id,
                    "name": fallback.get("name") or f"Station {terminal}",
                    "terminal": terminal,
                    "status": STATUS_RUNNING if is_running else STATUS_IDLE,
                    "isRunning": is_running,
                    "lastRun": history.get("last_started"),
                    "lastRunCompleted": history.get("last_completed"),
                    "lastDurationMinutes": history.get("last_duration_minutes"),
                    "plannedDurationMinutes": history.get(
                        "planned_duration_minutes"
                    ),
                }
            )
        return stations

    def _fetch_data(self) -> dict[str, Any]:
        now = datetime.now()
        local_reachable = False
        local_data_stale = False
        local_error: str | None = None
        active_zones: set[int] = set()

        try:
            active_zones = self.local_api.get_active_zones()
        except RainBirdAuthError as err:
            local_error = str(err)
            self._local_consecutive_errors += 1
        except Exception as err:
            local_error = str(err)
            self._local_consecutive_errors += 1
            if self._expected_terminal is not None:
                local_reachable = True
                local_data_stale = True
                active_zones = {self._expected_terminal}
            elif (
                self._local_last_success is not None
                and now - self._local_last_success <= self._local_status_grace
            ):
                local_reachable = True
                local_data_stale = True
                active_zones = set(self._local_last_active_zones)
        else:
            local_reachable = True
            self._local_last_success = now
            self._local_last_active_zones = set(active_zones)
            self._local_consecutive_errors = 0
            if (
                self._expected_terminal is not None
                and self._expected_terminal not in active_zones
                and self._expected_started is not None
                and now - self._expected_started < timedelta(seconds=45)
            ):
                active_zones.add(self._expected_terminal)
            elif (
                self._expected_terminal is not None
                and self._expected_terminal not in active_zones
            ):
                self._expected_terminal = None
                self._expected_started = None

        if not local_reachable and self.data:
            active_zones = {
                int(station["terminal"])
                for station in self.data.get("stations", [])
                if station.get("isRunning") and station.get("terminal") is not None
            }
        elif not local_reachable:
            active_zones = {
                int(station["terminal"])
                for station in self.fallback_stations
                if station.get("terminal") is not None
                and self.run_history.station(int(station["id"])).get("is_running")
            }
            if active_zones:
                local_reachable = True
                local_data_stale = True

        stations = self._stations(active_zones)
        return {
            "controller": {
                "id": self.controller_id,
                "name": self.controller_name,
                "model": "Rain Bird RC2",
                "serialNumber": self.serial_number,
            },
            "connection": {
                "isConnected": local_reachable,
                "connectionSource": "LAN" if local_reachable else "brak",
                "localConfigured": True,
                "localReachable": local_reachable,
                "localDataStale": local_data_stale,
                "localConsecutiveErrors": self._local_consecutive_errors,
                "localLastSuccess": (
                    self._local_last_success.isoformat()
                    if self._local_last_success
                    else None
                ),
                "localError": local_error,
                "localEndpoint": self.local_api.endpoint,
                "localActiveZones": sorted(active_zones),
                "localAvailableZones": sorted(self.available_zones),
            },
            "stations": stations,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self.hass.async_add_executor_job(self._fetch_data)
        await self.run_history.async_sync_station_states(data["stations"])
        for station in data["stations"]:
            history = self.run_history.station(int(station["id"]))
            station["lastRun"] = history.get("last_started")
            station["lastRunCompleted"] = history.get("last_completed")
            station["lastDurationMinutes"] = history.get(
                "last_duration_minutes"
            )
            station["plannedDurationMinutes"] = history.get(
                "planned_duration_minutes"
            )
        return data
