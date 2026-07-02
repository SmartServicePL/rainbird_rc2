"""Shared entities and helpers for Rain Bird RC2."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEFAULT_DURATION, DEFAULT_DURATION, DOMAIN


def controller_device_info(
    controller_id: str,
    coordinator,
) -> DeviceInfo:
    """Return device registry information for the RC2 controller."""
    controller = (coordinator.data or {}).get("controller", {})
    return DeviceInfo(
        identifiers={(DOMAIN, str(controller_id))},
        name=controller.get("name") or "Rain Bird RC2",
        manufacturer="Rain Bird",
        model=controller.get("model") or "Rain Bird RC2",
        serial_number=controller.get("serialNumber"),
    )


def find_by_id(items: list[dict[str, Any]], item_id: int) -> dict[str, Any]:
    """Find a station by numeric identifier."""
    return next(
        (item for item in items if int(item.get("id", -1)) == item_id),
        {},
    )


def station_display_name(station: dict[str, Any]) -> str:
    """Return the Rain Bird station description or a clean section fallback."""
    terminal = station.get("terminal")
    try:
        section_number = int(terminal)
    except (TypeError, ValueError):
        section_number = None
    fallback = f"Sekcja {section_number}" if section_number else "Sekcja"

    raw_name = str(station.get("name") or "").strip()
    if not raw_name:
        return fallback

    default_name = re.fullmatch(
        r"(station|zone|sekcja|stacja)\s*#?\s*\d+",
        raw_name.casefold(),
    )
    if default_name or raw_name.casefold() in {"station", "zone", "sekcja", "stacja"}:
        return fallback
    return raw_name


def default_manual_duration(runtime: dict[str, Any]) -> int:
    """Return the configured manual watering duration in minutes."""
    entry = runtime.get("entry")
    options = getattr(entry, "options", {}) or {}
    try:
        value = int(options.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION))
    except (TypeError, ValueError):
        return DEFAULT_DURATION
    return min(240, max(1, value))


class RainBirdRC2Entity(CoordinatorEntity):
    """Base coordinator entity attached to one RC2 device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._controller_id = str(coordinator.controller_id)
        self._satellite_id = self._controller_id

    @property
    def device_info(self) -> DeviceInfo:
        return controller_device_info(self._controller_id, self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "config_entry_id": self._entry_id,
            "controller_id": self._controller_id,
        }
