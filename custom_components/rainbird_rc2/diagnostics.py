"""Diagnostics support for Rain Bird RC2."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LOCAL_PASSWORD, DOMAIN

TO_REDACT = {CONF_LOCAL_PASSWORD, "password", "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return safe controller state without credentials."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "local_controller": runtime["realtime"].data,
        "run_history": {
            str(station["id"]): runtime["history"].station(int(station["id"]))
            for station in (runtime["realtime"].data or {}).get("stations", [])
        },
    }
