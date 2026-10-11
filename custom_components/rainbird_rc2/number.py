"""Number entities for Rain Bird RC2."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEFAULT_DURATION, DOMAIN
from .entity import RainBirdRC2Entity, default_manual_duration


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create editable RC2 runtime settings."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainBirdDefaultDurationNumber(runtime, entry.entry_id)])


class RainBirdDefaultDurationNumber(RainBirdRC2Entity, NumberEntity):
    """Set the default duration used by manual station switches."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_icon = "mdi:timer-outline"
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "default_manual_duration"
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(self, runtime: dict[str, Any], entry_id: str) -> None:
        super().__init__(runtime["realtime"], entry_id)
        self._runtime = runtime
        self._entry: ConfigEntry = runtime["entry"]
        self._attr_unique_id = f"{self._satellite_id}_default_manual_duration"

    @property
    def native_value(self) -> int:
        return default_manual_duration(self._runtime)

    async def async_set_native_value(self, value: float) -> None:
        """Persist the manual watering duration in the config entry options."""
        minutes = min(240, max(1, int(round(value))))
        options = dict(self._entry.options)
        options[CONF_DEFAULT_DURATION] = minutes
        changed = self.hass.config_entries.async_update_entry(
            self._entry,
            options=options,
        )
        if not changed:
            self.async_write_ha_state()
