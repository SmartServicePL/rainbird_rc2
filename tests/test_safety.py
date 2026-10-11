"""Tests for run safety, service resolution and configuration handling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import custom_components.rainbird_rc2 as integration
from custom_components.rainbird_rc2 import run_history as run_history_module
from custom_components.rainbird_rc2 import run_manager as run_manager_module
from custom_components.rainbird_rc2.config_flow import reauth_options
from custom_components.rainbird_rc2.const import (
    CONF_DEFAULT_DURATION,
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_VERIFY_SSL,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.rainbird_rc2.exceptions import RainBirdConnectionError
from custom_components.rainbird_rc2.run_history import (
    STARTED_BY_CONTROLLER,
    STARTED_BY_HA,
    RainBirdRunHistory,
)
from custom_components.rainbird_rc2.run_manager import RainBirdRunManager


class FakeStore:
    def __init__(self) -> None:
        self.saved = None

    async def async_save(self, data) -> None:
        self.saved = data


@pytest.fixture(autouse=True)
def real_clock(monkeypatch):
    """Use the real UTC clock regardless of the Home Assistant test environment."""

    def parse(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    monkeypatch.setattr(
        run_history_module,
        "dt_util",
        SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc), parse_datetime=parse),
    )
    monkeypatch.setattr(run_manager_module, "_STOP_RETRY_DELAY", 0)


def _history(stations=None) -> RainBirdRunHistory:
    history = object.__new__(RainBirdRunHistory)
    history._store = FakeStore()
    history._stations = stations or {}
    return history


class FakeHass:
    def __init__(self) -> None:
        self.tasks = []
        self.data = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_create_task(self, coro, name=None):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task


class FakeCoordinator:
    def __init__(self, stations) -> None:
        self.data = {"stations": stations}
        self.expected = None

    def set_expected_run(self, terminal, duration) -> None:
        self.expected = (terminal, duration)

    def clear_expected_run(self) -> None:
        self.expected = None


class FakeLocalAPI:
    def __init__(self, stop_failures: int = 0) -> None:
        self.stop_failures = stop_failures
        self.stop_calls = 0
        self.started = []

    def irrigate_zone(self, terminal, minutes) -> None:
        self.started.append((terminal, minutes))

    def stop_irrigation(self) -> None:
        self.stop_calls += 1
        if self.stop_calls <= self.stop_failures:
            raise RainBirdConnectionError("controller busy")


def test_reauth_removes_old_connection_settings_from_options() -> None:
    options = {
        CONF_LOCAL_HOST: "10.0.0.2",
        CONF_LOCAL_PASSWORD: "old-pin",
        CONF_LOCAL_VERIFY_SSL: False,
        CONF_DEFAULT_DURATION: 12,
        CONF_SCAN_INTERVAL: 45,
    }

    assert reauth_options(options) == {CONF_DEFAULT_DURATION: 12, CONF_SCAN_INTERVAL: 45}


def test_changing_default_duration_does_not_reload_or_stop_a_run() -> None:
    entry = SimpleNamespace(
        entry_id="entry",
        data={CONF_LOCAL_HOST: "10.0.0.2", CONF_LOCAL_PASSWORD: "1234"},
        options={CONF_DEFAULT_DURATION: 10},
    )
    reloads = []

    async def reload(entry_id):
        reloads.append(entry_id)

    hass = SimpleNamespace(
        data={DOMAIN: {"entry": {"connection_snapshot": integration.connection_snapshot(entry)}}},
        config_entries=SimpleNamespace(async_reload=reload),
    )

    entry.options = {CONF_DEFAULT_DURATION: 25}
    asyncio.run(integration.async_update_options(hass, entry))
    assert reloads == []

    entry.options = {CONF_DEFAULT_DURATION: 25, CONF_LOCAL_PASSWORD: "5678"}
    asyncio.run(integration.async_update_options(hass, entry))
    assert reloads == ["entry"]


def test_controller_started_run_drops_old_planned_duration() -> None:
    history = _history(
        {"1001": {"is_running": False, "planned_duration_minutes": 5, "started_by": STARTED_BY_HA}}
    )

    asyncio.run(history.async_sync_station_states([{"id": 1001, "isRunning": True}]))

    item = history.station(1001)
    assert item["is_running"] is True
    assert item["started_by"] == STARTED_BY_CONTROLLER
    assert "planned_duration_minutes" not in item


def test_ha_started_run_is_marked_and_keeps_duration() -> None:
    history = _history()

    asyncio.run(history.async_mark_started(1001, 12))

    item = history.station(1001)
    assert item["started_by"] == STARTED_BY_HA
    assert item["planned_duration_minutes"] == 12


def _resume(item) -> bool:
    async def run() -> bool:
        hass = FakeHass()
        history = _history({"1001": item})
        coordinator = FakeCoordinator([{"id": 1001, "terminal": 1}])
        manager = RainBirdRunManager(hass, FakeLocalAPI(), coordinator, history)
        await manager.async_resume_from_history()
        armed = manager._auto_stop_task is not None
        manager._cancel_auto_stop()
        await asyncio.sleep(0)
        return armed

    return asyncio.run(run())


def test_resume_rearms_stop_only_for_runs_started_by_ha() -> None:
    started = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    base = {"is_running": True, "last_started": started, "planned_duration_minutes": 30}

    assert _resume(dict(base, started_by=STARTED_BY_HA)) is True
    assert _resume(dict(base, started_by=STARTED_BY_CONTROLLER)) is False
    assert _resume(dict(base)) is False


def test_automatic_stop_is_retried_until_rc2_confirms() -> None:
    async def run():
        hass = FakeHass()
        history = _history()
        coordinator = FakeCoordinator([{"id": 1001, "terminal": 1}])
        api = FakeLocalAPI(stop_failures=2)
        manager = RainBirdRunManager(hass, api, coordinator, history)
        await manager.async_start(1001, 1, 1)
        manager._cancel_auto_stop()
        await asyncio.sleep(0)
        await manager._async_auto_stop(0)
        return api, history, coordinator

    api, history, coordinator = asyncio.run(run())

    assert api.stop_calls == 3
    assert history.station(1001)["is_running"] is False
    assert coordinator.expected is None


def test_stop_service_resolves_unavailable_station_through_registry(monkeypatch) -> None:
    runtime = {
        "local_api": object(),
        "realtime": SimpleNamespace(
            data={"stations": [{"id": 1002, "terminal": 2}]},
            fallback_stations=[],
        ),
    }
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": runtime}}, states=SimpleNamespace(get=lambda _e: None))
    entry = SimpleNamespace(
        platform=DOMAIN,
        unique_id="522237_station_1002_manual_switch",
        config_entry_id="entry-1",
    )
    registry = SimpleNamespace(async_get=lambda entity_id: entry if entity_id == "switch.lawn" else None)
    monkeypatch.setattr(integration, "er", SimpleNamespace(async_get=lambda _hass: registry))

    resolved_runtime, station_id, terminal = integration._runtime_and_station_for_entity(hass, "switch.lawn")

    assert resolved_runtime is runtime
    assert (station_id, terminal) == (1002, 2)
