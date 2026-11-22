"""Configurazione: preferito del browser (consigliato) o cookie (avanzato)."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import http
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .api import (
    PortaleConsumiApi,
    PortaleConsumiAuthError,
    PortaleConsumiError,
    PortaleConsumiSessionSuspect,
    async_build_ssl_context,
    create_session,
)
from .browser import START_PATH, key_hash
from .browser_views import FLOW_SERIES, async_register_views, get_pending
from .const import (
    CONF_COOKIE_HEADER,
    CONF_KEY_HASH,
    CONF_MODE,
    CONF_RECEIVED_AT,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SERIES,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
    MODE_BROWSER,
    MODE_COOKIE,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

HEADER_FRONTEND_BASE = "HA-Frontend-Base"  # stessa fonte di HA per gli external step OAuth2


def _frontend_base(hass: HomeAssistant) -> str:
    """Origine da cui l'utente sta usando HA (il frontend scarta gli URL relativi)."""
    req = http.current_request.get()
    if req is not None:
        base = (req.headers.get(HEADER_FRONTEND_BASE) or "").rstrip("/")
        if re.fullmatch(r"https?://[^/?#@\s]+", base):
            return base
    return get_url(hass, allow_internal=True, allow_external=True, prefer_external=False).rstrip("/")


def _interval_validator():
    return vol.All(
        vol.Coerce(int),
        vol.Range(min=MIN_SCAN_INTERVAL_HOURS, max=MAX_SCAN_INTERVAL_HOURS),
    )


def _cookie_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_COOKIE_HEADER): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            )
        }
    )


async def _validate_cookie(hass: HomeAssistant, cookie: str) -> str | None:
    """Verifica la sessione con una richiesta al servizio forniture."""
    ssl_context = await async_build_ssl_context(hass)
    async with create_session(ssl_context, total_timeout=30) as session:
        try:
            api = PortaleConsumiApi(session, cookie)
            await api.get_forniture_elettriche()
        except (PortaleConsumiAuthError, PortaleConsumiSessionSuspect) as err:
            # Appena incollato: un 503 API_INVALID_RESPONSE è quasi sempre il
            # cookie sbagliato o scaduto.
            _LOGGER.warning("Validazione della sessione SII fallita: %s", err)
            return "invalid_session"
        except PortaleConsumiError as err:
            _LOGGER.warning("Validazione della sessione SII fallita: %s", err)
            return "cannot_connect"
    return None


class ConsumiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configura Consumi luce e gas (SII)."""

    VERSION = 1

    def __init__(self) -> None:
        self._target: config_entries.ConfigEntry | None = None
        self._key: str | None = None
        self._series: dict[str, Any] | None = None
        self._browser_error: str | None = None

    # ------------------------------------------------------------ ingressi
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(step_id="user", menu_options=["browser", "cookie"])

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        self._target = self._get_reauth_entry()
        return self.async_show_menu(step_id="reauth_confirm", menu_options=["browser", "cookie"])

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        self._target = self._get_reconfigure_entry()
        return self.async_show_menu(step_id="reconfigure", menu_options=["browser", "cookie"])

    # ------------------------------------------------------------ preferito
    async def async_step_browser(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """External step: HA apre la pagina di avvio; la ricezione torna qui."""
        pending = get_pending(self.hass)
        if user_input is None:
            try:
                base = _frontend_base(self.hass)
            except NoURLAvailableError:
                self._browser_error = "no_url"
                return await self.async_step_cookie()
            async_register_views(self.hass)
            self._key = pending.create(self.flow_id)
            return self.async_external_step(
                step_id="browser",
                url=f"{base}{START_PATH}?flow_id={self.flow_id}&key={self._key}",
            )

        series = user_input.get(FLOW_SERIES)
        if not isinstance(series, dict) or not series:
            pending.set_outcome(self.flow_id, "no_points")
            return self.async_external_step_done(next_step_id="browser_failed")
        self._series = series
        pending.set_outcome(self.flow_id, "ok_setup")
        return self.async_external_step_done(next_step_id="browser_done")

    async def async_step_browser_failed(self, user_input=None) -> ConfigFlowResult:
        return self.async_abort(reason="no_points")

    async def async_step_browser_done(self, user_input=None) -> ConfigFlowResult:
        assert self._key is not None and self._series is not None
        data = {
            CONF_MODE: MODE_BROWSER,
            CONF_KEY_HASH: key_hash(self._key),
            CONF_SERIES: self._series,
            CONF_RECEIVED_AT: dt_util.utcnow().isoformat(),
        }
        if self._target is None:
            return self.async_create_entry(title=NAME, data=data)
        return self.async_update_reload_and_abort(
            self._target, data=data, reason=self._success_reason
        )

    # ------------------------------------------------------------ cookie
    async def async_step_cookie(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._browser_error:
            errors["base"] = self._browser_error
            self._browser_error = None
        if user_input is not None:
            cookie = str(user_input[CONF_COOKIE_HEADER]).strip()
            error = await _validate_cookie(self.hass, cookie)
            if error is None:
                data = {CONF_MODE: MODE_COOKIE, CONF_COOKIE_HEADER: cookie}
                if self._target is None:
                    return self.async_create_entry(
                        title=NAME,
                        data=data,
                        options={CONF_SCAN_INTERVAL_HOURS: DEFAULT_SCAN_INTERVAL_HOURS},
                    )
                return self.async_update_reload_and_abort(
                    self._target, data=data, reason=self._success_reason
                )
            errors["base"] = error
        return self.async_show_form(step_id="cookie", data_schema=_cookie_schema(), errors=errors)

    @property
    def _success_reason(self) -> str:
        if self.source == config_entries.SOURCE_REAUTH:
            return "reauth_successful"
        return "reconfigure_successful"

    @staticmethod
    def async_get_options_flow(config_entry):
        return ConsumiOptionsFlow()


class ConsumiOptionsFlow(config_entries.OptionsFlow):
    """Intervallo di aggiornamento (solo modalità cookie)."""

    async def async_step_init(self, user_input=None):
        if self.config_entry.data.get(CONF_MODE) == MODE_BROWSER:
            return self.async_abort(reason="browser_no_options")
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_SCAN_INTERVAL_HOURS: user_input[CONF_SCAN_INTERVAL_HOURS]},
            )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCAN_INTERVAL_HOURS, default=current): _interval_validator()}
            ),
        )
