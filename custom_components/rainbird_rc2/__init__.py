"""Rain Bird RC2 integration using the local controller API."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_VERIFY_SSL,
    CONF_SATELLITE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import RainBirdCoordinator
from .entity import default_manual_duration
from .exceptions import RainBirdAuthError, RainBirdConnectionError
from .local_api import RainBirdLocalAPI
from .run_history import RainBirdRunHistory
from .run_manager import RainBirdRunManager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
]

_STATION_ENTITY_RE = re.compile(
    r"^(?P<controller>.+)_station_(?P<station>\d+)_(?P<kind>status|manual_switch)$"
)


def _integration_runtimes(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, dict) and "local_api" in value
    ]


def _runtime_for_entry(hass: HomeAssistant, entry_id: str | None) -> dict[str, Any]:
    if entry_id:
        runtime = hass.data.get(DOMAIN, {}).get(entry_id)
        if isinstance(runtime, dict) and "local_api" in runtime:
            return runtime
        raise ServiceValidationError("The selected Rain Bird RC2 entry is unavailable")
    runtimes = _integration_runtimes(hass)
    if len(runtimes) != 1:
        raise ServiceValidationError(
            "Select a Rain Bird RC2 config entry when more than one controller exists"
        )
    return runtimes[0]


def station_terminal(runtime: dict[str, Any], station_id: int) -> int | None:
    """Return the RC2 terminal of a station from live data or registry fallbacks."""
    realtime = runtime["realtime"]
    sources = list((realtime.data or {}).get("stations", [])) + list(
        getattr(realtime, "fallback_stations", []) or []
    )
    for station in sources:
        try:
            if int(station.get("id", -1)) == station_id and station.get(
                "terminal"
            ) is not None:
                return int(station["terminal"])
        except (TypeError, ValueError):
            continue
    return None


def _runtime_and_station_for_entity(
    hass: HomeAssistant,
    entity_id: str,
) -> tuple[dict[str, Any], int, int]:
    """Resolve a station switch through the entity registry.

    The registry is used instead of state attributes, so a stop command still
    works while the station entity is temporarily unavailable.
    """
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None or entity_entry.platform != DOMAIN:
        raise ServiceValidationError(
            f"Entity {entity_id} is not a Rain Bird RC2 station entity"
        )
    match = _STATION_ENTITY_RE.match(entity_entry.unique_id or "")
    if match is None or match.group("kind") != "manual_switch":
        raise ServiceValidationError(
            f"Entity {entity_id} is not a Rain Bird RC2 station switch"
        )
    runtime = _runtime_for_entry(hass, entity_entry.config_entry_id)
    station_id = int(match.group("station"))
    terminal = station_terminal(runtime, station_id)
    if terminal is None:
        raise ServiceValidationError(
            f"Rain Bird RC2 terminal for {entity_id} is not known yet"
        )
    return runtime, station_id, terminal


def _station_fallbacks_from_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controller_id: str,
) -> list[dict[str, Any]]:
    """Preserve station names and cloud-era IDs during the local migration."""
    registry = er.async_get(hass)
    stations: dict[int, dict[str, Any]] = {}
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        match = _STATION_ENTITY_RE.match(entity_entry.unique_id or "")
        if not match or match.group("controller") != controller_id:
            continue
        station_id = int(match.group("station"))
        state = hass.states.get(entity_entry.entity_id)
        terminal = state.attributes.get("terminal") if state else None
        name = (
            getattr(entity_entry, "name", None)
            or getattr(entity_entry, "name_by_user", None)
            or getattr(entity_entry, "original_name", None)
            or entity_entry.entity_id
        )
        for suffix in (" stan", " status"):
            if name.casefold().endswith(suffix):
                name = name[: -len(suffix)]
        current = stations.get(station_id, {})
        stations[station_id] = {
            "id": station_id,
            "name": current.get("name") or name,
            "terminal": terminal or current.get("terminal"),
        }

    ordered = sorted(stations.values(), key=lambda item: int(item["id"]))
    used_terminals = {
        int(item["terminal"]) for item in ordered if item.get("terminal") is not None
    }
    next_terminal = 1
    for station in ordered:
        if station.get("terminal") is not None:
            continue
        while next_terminal in used_terminals:
            next_terminal += 1
        station["terminal"] = next_terminal
        used_terminals.add(next_terminal)
    return ordered


def _cleanup_legacy_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controller_id: str,
) -> None:
    """Remove cloud-only and duplicate entities from the entity registry."""
    registry = er.async_get(hass)
    exact_unique_ids = {
        f"{controller_id}_controller_mode",
        f"{controller_id}_connection_type",
        f"{controller_id}_schedule_enabled",
        f"{controller_id}_alarms",
        f"{controller_id}_warnings",
        f"{controller_id}_forecast_enabled",
    }
    station_status_re = re.compile(
        rf"^{re.escape(controller_id)}_station_\d+_status$"
    )
    physical_sensor_re = re.compile(
        rf"^{re.escape(controller_id)}_sensor_\d+$"
    )
    for entity_entry in list(
        er.async_entries_for_config_entry(registry, entry.entry_id)
    ):
        unique_id = entity_entry.unique_id or ""
        if (
            unique_id in exact_unique_ids
            or station_status_re.match(unique_id)
            or physical_sensor_re.match(unique_id)
        ):
            registry.async_remove(entity_entry.entity_id)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register local RC2 services once."""
    hass.data.setdefault(DOMAIN, {})

    async def handle_start_zone(call: ServiceCall) -> None:
        runtime, station_id, terminal = _runtime_and_station_for_entity(
            hass, call.data["station_entity"]
        )
        duration = int(call.data.get("duration") or default_manual_duration(runtime))
        try:
            await runtime["run_manager"].async_start(
                station_id,
                terminal,
                duration,
            )
        except RainBirdAuthError as err:
            raise HomeAssistantError(
                f"Local RC2 authentication failed: {err}"
            ) from err
        except RainBirdConnectionError as err:
            raise HomeAssistantError(f"Local RC2 command failed: {err}") from err

    async def handle_stop_zone(call: ServiceCall) -> None:
        runtime, station_id, _terminal = _runtime_and_station_for_entity(
            hass, call.data["station_entity"]
        )
        try:
            await runtime["run_manager"].async_stop(station_id)
        except RainBirdAuthError as err:
            raise HomeAssistantError(
                f"Local RC2 authentication failed: {err}"
            ) from err
        except RainBirdConnectionError as err:
            raise HomeAssistantError(f"Local RC2 stop failed: {err}") from err

    async def handle_stop_all(call: ServiceCall) -> None:
        runtime = _runtime_for_entry(hass, call.data.get("config_entry_id"))
        try:
            await runtime["run_manager"].async_stop()
        except RainBirdAuthError as err:
            raise HomeAssistantError(
                f"Local RC2 authentication failed: {err}"
            ) from err
        except RainBirdConnectionError as err:
            raise HomeAssistantError(f"Local RC2 stop-all failed: {err}") from err

    schemas = {
        "start_zone": vol.Schema(
            {
                vol.Required("station_entity"): cv.entity_id,
                vol.Optional("duration"): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=240)
                ),
            }
        ),
        "stop_zone": vol.Schema({vol.Required("station_entity"): cv.entity_id}),
        "stop_all": vol.Schema({vol.Optional("config_entry_id"): str}),
    }
    services = {
        "start_zone": (handle_start_zone, schemas["start_zone"]),
        "stop_zone": (handle_stop_zone, schemas["stop_zone"]),
        "stop_all": (handle_stop_all, schemas["stop_all"]),
    }
    for service, (handler, schema) in services.items():
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(DOMAIN, service, handler, schema=schema)
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Migrate cloud-era entries to the local-only config flow version."""
    if entry.version < 2:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


def _probe_local_controller(
    local_api: RainBirdLocalAPI,
) -> tuple[str | None, set[int]]:
    serial_number: str | None = None
    try:
        serial_number = local_api.get_serial_number() or None
    except RainBirdConnectionError:
        pass
    return serial_number, local_api.get_available_zones()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one RC2 using only its local LAN endpoint."""
    options = entry.options
    local_host = str(
        options.get(CONF_LOCAL_HOST) or entry.data.get(CONF_LOCAL_HOST) or ""
    ).strip()
    local_password = str(
        options.get(CONF_LOCAL_PASSWORD)
        or entry.data.get(CONF_LOCAL_PASSWORD)
        or ""
    ).strip()
    if not local_host or not local_password:
        raise ConfigEntryNotReady(
            "Configure the local RC2 address and controller PIN in integration options"
        )

    local_api = RainBirdLocalAPI(
        local_host,
        local_password,
        verify_ssl=bool(
            options.get(
                CONF_LOCAL_VERIFY_SSL,
                entry.data.get(CONF_LOCAL_VERIFY_SSL, False),
            )
        ),
    )
    try:
        serial_number, available_zones = await hass.async_add_executor_job(
            _probe_local_controller,
            local_api,
        )
    except RainBirdAuthError as err:
        await hass.async_add_executor_job(local_api.close)
        raise ConfigEntryAuthFailed("Rain Bird RC2 rejected the local PIN") from err
    except Exception as err:
        await hass.async_add_executor_job(local_api.close)
        raise ConfigEntryNotReady(
            f"Unable to connect to the local Rain Bird RC2: {err}"
        ) from err

    if not available_zones:
        await hass.async_add_executor_job(local_api.close)
        raise ConfigEntryNotReady("The local RC2 did not report any stations")

    controller_id = str(
        entry.data.get(CONF_SATELLITE_ID)
        or entry.unique_id
        or serial_number
        or entry.entry_id
    )
    fallback_stations = _station_fallbacks_from_registry(
        hass,
        entry,
        controller_id,
    )
    history = RainBirdRunHistory(hass, entry.entry_id)
    await history.async_load()
    realtime = RainBirdCoordinator(
        hass,
        local_api,
        controller_id,
        entry.title or DEFAULT_NAME,
        int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        available_zones,
        history,
        fallback_stations,
        serial_number,
        config_entry=entry,
    )
    await realtime.async_config_entry_first_refresh()
    run_manager = RainBirdRunManager(
        hass,
        local_api,
        realtime,
        history,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "entry": entry,
        "local_api": local_api,
        "realtime": realtime,
        "history": history,
        "run_manager": run_manager,
        "connection_snapshot": connection_snapshot(entry),
    }
    await run_manager.async_resume_from_history()
    _cleanup_legacy_entities(hass, entry, controller_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


def connection_snapshot(entry: ConfigEntry) -> dict[str, Any]:
    """Return the settings that require a new connection when changed."""
    options = entry.options
    return {
        CONF_LOCAL_HOST: options.get(CONF_LOCAL_HOST)
        or entry.data.get(CONF_LOCAL_HOST),
        CONF_LOCAL_PASSWORD: options.get(CONF_LOCAL_PASSWORD)
        or entry.data.get(CONF_LOCAL_PASSWORD),
        CONF_LOCAL_VERIFY_SSL: options.get(
            CONF_LOCAL_VERIFY_SSL, entry.data.get(CONF_LOCAL_VERIFY_SSL, False)
        ),
        CONF_SCAN_INTERVAL: options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    }


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only for connection changes.

    A reload stops an HA-managed run, so changing the default manual duration
    (read live from the options) must not reload the entry.
    """
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime and runtime.get("connection_snapshot") == connection_snapshot(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
        if runtime:
            await runtime["run_manager"].async_shutdown()
            await hass.async_add_executor_job(runtime["local_api"].close)
    return unload_ok
