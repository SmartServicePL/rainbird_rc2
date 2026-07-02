"""Reliable local run timing for Rain Bird RC2 stations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from homeassistant.core import HomeAssistant

from .coordinator import RainBirdCoordinator
from .exceptions import RainBirdAuthError, RainBirdConnectionError
from .local_api import RainBirdLocalAPI
from .run_history import RainBirdRunHistory

_LOGGER = logging.getLogger(__name__)
_STOP_RETRY_DELAY = 5
_MANUAL_STOP_ATTEMPTS = 3


class RainBirdRunManager:
    """Enforce RC2 run duration independently of controller firmware."""

    def __init__(
        self,
        hass: HomeAssistant,
        local_api: RainBirdLocalAPI,
        coordinator: RainBirdCoordinator,
        history: RainBirdRunHistory,
    ) -> None:
        self._hass = hass
        self._local_api = local_api
        self._coordinator = coordinator
        self._history = history
        self._command_lock = asyncio.Lock()
        self._auto_stop_task: asyncio.Task[None] | None = None
        self._station_id: int | None = None
        self._terminal: int | None = None

    async def async_start(
        self,
        station_id: int,
        terminal: int,
        duration_minutes: int,
    ) -> None:
        """Start a station and arm an HA-side stop timer."""
        duration = max(1, int(duration_minutes))
        async with self._command_lock:
            if self._station_id is not None:
                await self._async_send_stop(_MANUAL_STOP_ATTEMPTS)
                self._cancel_auto_stop()
                await self._async_finish_stop()
            await self._hass.async_add_executor_job(
                self._local_api.irrigate_zone,
                terminal,
                duration,
            )
            self._station_id = station_id
            self._terminal = terminal
            await self._history.async_mark_started(station_id, duration)
            self._coordinator.set_expected_run(terminal, duration)
            self._auto_stop_task = self._hass.async_create_task(
                self._async_auto_stop(duration * 60),
                name=f"rainbird_rc2_auto_stop_{station_id}",
            )

    async def async_stop(self, station_id: int | None = None) -> None:
        """Stop irrigation after the RC2 acknowledges the command."""
        async with self._command_lock:
            await self._async_send_stop(_MANUAL_STOP_ATTEMPTS)
            self._cancel_auto_stop()
            await self._async_finish_stop(station_id)

    async def async_resume_from_history(self) -> None:
        """Restore a pending safety timer after an integration reload."""
        for station in (self._coordinator.data or {}).get("stations", []):
            station_id = int(station["id"])
            item = self._history.station(station_id)
            if not item.get("is_running") or not item.get(
                "planned_duration_minutes"
            ):
                continue
            started = _parse_datetime(item.get("last_started"))
            if started is None:
                continue
            duration = int(item["planned_duration_minutes"])
            remaining = (
                started + timedelta(minutes=duration) - datetime.now(timezone.utc)
            ).total_seconds()
            self._station_id = station_id
            self._terminal = int(station["terminal"])
            self._coordinator.set_expected_run(
                self._terminal,
                max(1, int((max(0, remaining) + 59) // 60)),
            )
            self._auto_stop_task = self._hass.async_create_task(
                self._async_auto_stop(max(0, remaining)),
                name=f"rainbird_rc2_resume_stop_{station_id}",
            )
            break

    async def async_shutdown(self) -> None:
        """Stop an HA-managed run before unloading the integration."""
        if self._station_id is not None:
            try:
                async with self._command_lock:
                    await self._async_send_stop(_MANUAL_STOP_ATTEMPTS)
                    await self._async_finish_stop()
            except (RainBirdAuthError, RainBirdConnectionError) as err:
                _LOGGER.error("Unable to stop RC2 while unloading: %s", err)
        self._cancel_auto_stop()

    async def _async_auto_stop(self, delay_seconds: float) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            async with self._command_lock:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        await self._async_send_stop(1)
                        break
                    except (RainBirdAuthError, RainBirdConnectionError) as err:
                        _LOGGER.warning(
                            "RC2 automatic stop attempt %s failed: %s",
                            attempt,
                            err,
                        )
                        await asyncio.sleep(
                            _STOP_RETRY_DELAY if attempt < 20 else 30
                        )
                await self._async_finish_stop()
        except asyncio.CancelledError:
            raise
        finally:
            if self._auto_stop_task is asyncio.current_task():
                self._auto_stop_task = None

    async def _async_send_stop(self, attempts: int) -> None:
        last_error: RainBirdAuthError | RainBirdConnectionError | None = None
        for attempt in range(1, attempts + 1):
            try:
                await self._hass.async_add_executor_job(
                    self._local_api.stop_irrigation
                )
                return
            except RainBirdAuthError:
                raise
            except RainBirdConnectionError as err:
                last_error = err
                if attempt < attempts:
                    await asyncio.sleep(_STOP_RETRY_DELAY)
        if last_error is not None:
            raise last_error

    async def _async_finish_stop(
        self,
        requested_station_id: int | None = None,
    ) -> None:
        station_ids = {
            station_id
            for station_id in (self._station_id, requested_station_id)
            if station_id is not None
            and self._history.station(station_id).get("is_running")
        }
        for station_id in station_ids:
            await self._history.async_mark_completed(station_id)
        self._coordinator.clear_expected_run()
        self._station_id = None
        self._terminal = None

    def _cancel_auto_stop(self) -> None:
        task = self._auto_stop_task
        self._auto_stop_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
