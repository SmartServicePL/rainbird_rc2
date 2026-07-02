"""Switch entities for Rain Bird RC2."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    RainBirdRC2Entity,
    default_manual_duration,
    find_by_id,
    station_display_name,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create manual ON/OFF switches for RC2 stations."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    added_station_ids: set[int] = set()

    def add_station_switches() -> None:
        entities: list[SwitchEntity] = []
        sources = _station_switch_sources(runtime)
        for station in sources:
            station_id = int(station["id"])
            if station_id in added_station_ids:
                continue
            added_station_ids.add(station_id)
            entities.append(
                RainBirdStationSwitch(
                    runtime,
                    entry.entry_id,
                    station,
                )
            )
        if entities:
            async_add_entities(entities, True)

    add_station_switches()
    entry.async_on_unload(runtime["realtime"].async_add_listener(add_station_switches))


def _station_switch_sources(
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return RC2 station data for manual switches."""
    return list((runtime["realtime"].data or {}).get("stations", []))


class RainBirdStationSwitch(RainBirdRC2Entity, SwitchEntity):
    """Manual ON/OFF switch for one physical RC2 station."""

    _attr_icon = "mdi:sprinkler-variant"

    def __init__(
        self,
        runtime: dict[str, Any],
        entry_id: str,
        station: dict[str, Any],
    ) -> None:
        super().__init__(runtime["realtime"], entry_id)
        self._runtime = runtime
        self._station_id = int(station["id"])
        self._terminal = station.get("terminal")
        self._attr_unique_id = (
            f"{self._satellite_id}_station_{self._station_id}_manual_switch"
        )
        self._attr_name = station_display_name(station)

    def _station(self) -> dict[str, Any]:
        return find_by_id(
            (self.coordinator.data or {}).get("stations", []),
            self._station_id,
        )

    def _local_terminal(self) -> int | None:
        terminal = self._station().get("terminal", self._terminal)
        return int(terminal) if terminal is not None else None

    @property
    def is_on(self) -> bool:
        return bool(self._station().get("isRunning"))

    @property
    def available(self) -> bool:
        connection = (self.coordinator.data or {}).get("connection", {})
        return super().available and bool(connection.get("isConnected"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        history = self._runtime["history"].station(self._station_id)
        return {
            **super().extra_state_attributes,
            "station_id": self._station_id,
            "terminal": station.get("terminal"),
            "remaining": station.get("remaining"),
            "last_run": history.get("last_started") or station.get("lastRun"),
            "last_run_completed": history.get("last_completed")
            or station.get("lastRunCompleted"),
            "last_duration_minutes": history.get("last_duration_minutes"),
            "planned_duration_minutes": history.get(
                "planned_duration_minutes"
            ),
            "manual_duration_minutes": default_manual_duration(self._runtime),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the station for the default manual duration."""
        duration = default_manual_duration(self._runtime)
        terminal = self._local_terminal()
        if terminal is None:
            raise HomeAssistantError("Local RC2 connection is not configured")
        await self._runtime["run_manager"].async_start(
            self._station_id,
            terminal,
            duration,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the station."""
        await self._runtime["run_manager"].async_stop(self._station_id)
