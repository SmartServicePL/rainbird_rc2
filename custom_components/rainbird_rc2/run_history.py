"""Persistent local run history for Rain Bird RC2 stations."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
STARTED_BY_HA = "ha"
STARTED_BY_CONTROLLER = "controller"


class RainBirdRunHistory:
    """Store the last confirmed run independently for every station."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, dict[str, Any]]](
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.run_history",
        )
        self._stations: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load saved run data."""
        self._stations = await self._store.async_load() or {}

    def station(self, station_id: int) -> dict[str, Any]:
        """Return saved data for one station."""
        return dict(self._stations.get(str(station_id), {}))

    async def async_mark_started(
        self,
        station_id: int,
        duration_minutes: int | None = None,
    ) -> None:
        """Record a confirmed station start."""
        key = str(station_id)
        item = dict(self._stations.get(key, {}))
        if not item.get("is_running"):
            item["last_started"] = dt_util.utcnow().isoformat()
        item["is_running"] = True
        item["started_by"] = STARTED_BY_HA
        if duration_minutes is not None:
            item["planned_duration_minutes"] = int(duration_minutes)
        else:
            item.pop("planned_duration_minutes", None)
        self._stations[key] = item
        await self._store.async_save(self._stations)

    async def async_mark_completed(self, station_id: int) -> None:
        """Record a confirmed station stop."""
        key = str(station_id)
        item = dict(self._stations.get(key, {}))
        now = dt_util.utcnow()
        started = dt_util.parse_datetime(str(item.get("last_started", "")))
        item["is_running"] = False
        item["last_completed"] = now.isoformat()
        if started is not None:
            item["last_duration_minutes"] = round(
                max(0.0, (now - started).total_seconds() / 60),
                1,
            )
        self._stations[key] = item
        await self._store.async_save(self._stations)

    async def async_sync_station_states(
        self,
        stations: list[dict[str, Any]],
    ) -> None:
        """Persist runs started locally, in HA, or in the Rain Bird app."""
        changed = False
        now = dt_util.utcnow()
        for station in stations:
            station_id = int(station["id"])
            key = str(station_id)
            item = dict(self._stations.get(key, {}))
            was_running = bool(item.get("is_running"))
            is_running = bool(station.get("isRunning"))

            if is_running and not was_running:
                # Started by the controller's own program or the Rain Bird app.
                # A planned duration left from an older HA start must not be
                # used to arm an HA stop timer for this run.
                item["is_running"] = True
                item["last_started"] = now.isoformat()
                item["started_by"] = STARTED_BY_CONTROLLER
                item.pop("planned_duration_minutes", None)
                changed = True
            elif not is_running and was_running:
                item["is_running"] = False
                item["last_completed"] = now.isoformat()
                started = dt_util.parse_datetime(str(item.get("last_started", "")))
                if started is not None:
                    item["last_duration_minutes"] = round(
                        max(0.0, (now - started).total_seconds() / 60),
                        1,
                    )
                changed = True

            self._stations[key] = item

        if changed:
            await self._store.async_save(self._stations)
