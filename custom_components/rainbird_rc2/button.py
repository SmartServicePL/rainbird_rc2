"""Buttons for Rain Bird RC2."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainBirdRefreshButton(runtime, entry.entry_id)])


class RainBirdRefreshButton(RainBirdRC2Entity, ButtonEntity):
    _attr_name = "Odśwież dane"
    _attr_icon = "mdi:refresh"

    def __init__(self, runtime: dict, entry_id: str) -> None:
        super().__init__(runtime["realtime"], entry_id)
        self._runtime = runtime
        self._attr_unique_id = f"{self._satellite_id}_refresh"

    async def async_press(self) -> None:
        await self._runtime["realtime"].async_request_refresh()
