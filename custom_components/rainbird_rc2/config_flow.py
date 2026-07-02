"""Config flow for a locally connected Rain Bird RC2."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CONTROLLER_TYPE,
    CONF_DEFAULT_DURATION,
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_VERIFY_SSL,
    CONF_SATELLITE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_DURATION,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .exceptions import RainBirdAuthError, RainBirdConnectionError
from .local_api import RainBirdLocalAPI


def _probe_local_rc2(
    host: str,
    password: str,
    verify_ssl: bool,
) -> tuple[str | None, set[int]]:
    api = RainBirdLocalAPI(host, password, verify_ssl=verify_ssl)
    try:
        serial_number: str | None = None
        try:
            serial_number = api.get_serial_number() or None
        except RainBirdConnectionError:
            pass
        return serial_number, api.get_available_zones()
    finally:
        api.close()


def _entry_value(
    entry: config_entries.ConfigEntry,
    key: str,
    default: Any = None,
) -> Any:
    return entry.options.get(key, entry.data.get(key, default))


class RainBirdRC2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure direct LAN access to one RC2 controller."""

    VERSION = 2

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_LOCAL_HOST]).strip()
            password = str(user_input[CONF_LOCAL_PASSWORD]).strip()
            verify_ssl = bool(user_input.get(CONF_LOCAL_VERIFY_SSL, False))
            try:
                serial_number, available_zones = (
                    await self.hass.async_add_executor_job(
                        _probe_local_rc2,
                        host,
                        password,
                        verify_ssl,
                    )
                )
                if not available_zones:
                    raise RainBirdConnectionError(
                        "The controller did not report any stations"
                    )
            except RainBirdAuthError:
                errors["base"] = "invalid_auth"
            except RainBirdConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                controller_id = serial_number or host.casefold().rstrip("/")
                await self.async_set_unique_id(controller_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={
                        CONF_LOCAL_HOST: host,
                        CONF_LOCAL_PASSWORD: password,
                        CONF_LOCAL_VERIFY_SSL: verify_ssl,
                        CONF_SATELLITE_ID: controller_id,
                        CONF_CONTROLLER_TYPE: "Rain Bird RC2",
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCAL_HOST): str,
                    vol.Required(CONF_LOCAL_PASSWORD): str,
                    vol.Optional(CONF_LOCAL_VERIFY_SSL, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start local PIN renewal."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate and save a replacement local PIN."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        host = str(_entry_value(self._reauth_entry, CONF_LOCAL_HOST, ""))
        verify_ssl = bool(
            _entry_value(self._reauth_entry, CONF_LOCAL_VERIFY_SSL, False)
        )
        if user_input is not None:
            host = str(user_input[CONF_LOCAL_HOST]).strip()
            password = str(user_input[CONF_LOCAL_PASSWORD]).strip()
            try:
                _serial, available_zones = (
                    await self.hass.async_add_executor_job(
                        _probe_local_rc2,
                        host,
                        password,
                        verify_ssl,
                    )
                )
                if not available_zones:
                    raise RainBirdConnectionError
            except RainBirdAuthError:
                errors["base"] = "invalid_auth"
            except RainBirdConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                data = dict(self._reauth_entry.data)
                data[CONF_LOCAL_HOST] = host
                data[CONF_LOCAL_PASSWORD] = password
                data[CONF_LOCAL_VERIFY_SSL] = verify_ssl
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data=data,
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCAL_HOST, default=host): str,
                    vol.Required(CONF_LOCAL_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return RainBirdRC2OptionsFlow(config_entry)


class RainBirdRC2OptionsFlow(config_entries.OptionsFlow):
    """Configure local polling and manual runtime."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        if user_input is not None:
            options = dict(user_input)
            password = str(options.get(CONF_LOCAL_PASSWORD, "")).strip()
            if not password:
                existing = _entry_value(
                    self._config_entry,
                    CONF_LOCAL_PASSWORD,
                    "",
                )
                if existing:
                    options[CONF_LOCAL_PASSWORD] = existing
                else:
                    options.pop(CONF_LOCAL_PASSWORD, None)
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEFAULT_DURATION,
                        default=_entry_value(
                            self._config_entry,
                            CONF_DEFAULT_DURATION,
                            DEFAULT_DURATION,
                        ),
                    ): vol.All(int, vol.Range(min=1, max=240)),
                    vol.Required(
                        CONF_LOCAL_HOST,
                        default=_entry_value(
                            self._config_entry,
                            CONF_LOCAL_HOST,
                            "",
                        ),
                    ): str,
                    vol.Optional(CONF_LOCAL_PASSWORD, default=""): str,
                    vol.Optional(
                        CONF_LOCAL_VERIFY_SSL,
                        default=_entry_value(
                            self._config_entry,
                            CONF_LOCAL_VERIFY_SSL,
                            False,
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=_entry_value(
                            self._config_entry,
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL,
                        ),
                    ): vol.All(int, vol.Range(min=10, max=300)),
                }
            ),
        )
