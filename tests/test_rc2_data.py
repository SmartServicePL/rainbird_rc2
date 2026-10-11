"""Focused tests for local RC2 state and station mapping."""

import time

from custom_components.rainbird_rc2.coordinator import RainBirdCoordinator
from custom_components.rainbird_rc2.entity import station_display_name


class FakeHistory:
    def __init__(self) -> None:
        self.data = {
            1001: {
                "last_started": "2026-07-01T03:00:00+00:00",
                "last_completed": "2026-07-01T03:20:00+00:00",
                "last_duration_minutes": 20,
            }
        }

    def station(self, station_id):
        return dict(self.data.get(station_id, {}))


class FakeLocalAPI:
    endpoint = "https://local/stick"

    def __init__(self, responses):
        self.responses = list(responses)

    def get_active_zones(self):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _coordinator(responses) -> RainBirdCoordinator:
    coordinator = object.__new__(RainBirdCoordinator)
    coordinator.local_api = FakeLocalAPI(responses)
    coordinator.controller_id = "522237"
    coordinator.controller_name = "RC2 S16"
    coordinator.serial_number = "SERIAL"
    coordinator.available_zones = {1, 2}
    coordinator.run_history = FakeHistory()
    coordinator.fallback_stations = [
        {"id": 1001, "name": "Trawnik przed domem", "terminal": 1},
        {"id": 1002, "name": "Trawnik za domem", "terminal": 2},
    ]
    coordinator._local_last_success = None
    coordinator._local_last_success_at = None
    coordinator._local_last_active_zones = set()
    coordinator._local_consecutive_errors = 0
    coordinator._local_status_grace = 120.0
    coordinator._expected_terminal = None
    coordinator._expected_started = None
    coordinator._auth_failed = False
    coordinator.data = None
    return coordinator


def test_local_state_maps_active_terminal_to_station() -> None:
    coordinator = _coordinator([{1}])

    data = coordinator._fetch_data()

    assert data["connection"]["isConnected"] is True
    assert data["connection"]["connectionSource"] == "LAN"
    assert data["stations"][0]["id"] == 1001
    assert data["stations"][0]["isRunning"] is True
    assert data["stations"][0]["lastRunCompleted"] == "2026-07-01T03:20:00+00:00"
    assert data["stations"][1]["isRunning"] is False


def test_transient_local_error_keeps_last_confirmed_state() -> None:
    coordinator = _coordinator([{1}, RuntimeError("temporary timeout")])
    coordinator._fetch_data()

    transient = coordinator._fetch_data()

    assert transient["connection"]["isConnected"] is True
    assert transient["connection"]["localDataStale"] is True
    assert transient["connection"]["localConsecutiveErrors"] == 1
    assert transient["stations"][0]["isRunning"] is True


def test_expired_grace_marks_controller_offline_without_false_stop() -> None:
    coordinator = _coordinator([{1}, RuntimeError("network down")])
    first = coordinator._fetch_data()
    coordinator.data = first
    coordinator._local_last_success = time.monotonic() - 180

    offline = coordinator._fetch_data()

    assert offline["connection"]["isConnected"] is False
    assert offline["connection"]["localDataStale"] is False
    assert offline["stations"][0]["isRunning"] is True


def test_expected_run_stays_available_while_rc2_is_busy() -> None:
    coordinator = _coordinator([RuntimeError("controller busy")])
    coordinator._expected_terminal = 1
    coordinator._expected_started = time.monotonic() - 120

    data = coordinator._fetch_data()

    assert data["connection"]["isConnected"] is True
    assert data["connection"]["localDataStale"] is True
    assert data["stations"][0]["isRunning"] is True


def test_station_display_name_uses_clean_section_fallback() -> None:
    assert station_display_name({"name": "Station 3", "terminal": 3}) == "Sekcja 3"
    assert (
        station_display_name({"name": "Trawnik przed domem", "terminal": 1})
        == "Trawnik przed domem"
    )


def test_rejected_pin_is_flagged_for_reauthentication() -> None:
    from custom_components.rainbird_rc2.exceptions import RainBirdAuthError

    coordinator = _coordinator([RainBirdAuthError("403")])

    data = coordinator._fetch_data()

    assert coordinator._auth_failed is True
    assert data["connection"]["isConnected"] is False


def test_successful_poll_clears_rejected_pin_flag() -> None:
    coordinator = _coordinator([{1}])
    coordinator._auth_failed = True

    coordinator._fetch_data()

    assert coordinator._auth_failed is False
