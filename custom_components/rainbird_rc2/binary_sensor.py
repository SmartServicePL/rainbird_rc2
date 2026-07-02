"""Connection diagnostics for Rain Bird RC2."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import RainBirdRC2Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the one diagnostic entity needed by automations."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainBirdConnectionBinarySensor(runtime, entry.entry_id)])


class RainBirdConnectionBinarySensor(RainBirdRC2Entity, BinarySensorEntity):
    """Report confirmed local connectivity to the RC2."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"
    _attr_name = "Polaczenie lokalne"

    def __init__(self, runtime: dict, entry_id: str) -> None:
        super().__init__(runtime["realtime"], entry_id)
        self._attr_unique_id = f"{self._controller_id}_connected"

    @property
    def is_on(self) -> bool:
        return bool(
            (self.coordinator.data or {}).get("connection", {}).get("isConnected")
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        connection = (self.coordinator.data or {}).get("connection", {})
        return {
            **super().extra_state_attributes,
            "connection_source": connection.get("connectionSource"),
            "local_reachable": connection.get("localReachable"),
            "local_data_stale": connection.get("localDataStale"),
            "local_consecutive_errors": connection.get("localConsecutiveErrors"),
            "local_last_success": connection.get("localLastSuccess"),
            "local_error": connection.get("localError"),
            "local_endpoint": connection.get("localEndpoint"),
            "local_active_zones": connection.get("localActiveZones"),
            "local_available_zones": connection.get("localAvailableZones"),
        }
