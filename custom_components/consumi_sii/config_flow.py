"""Flusso di configurazione dell'integrazione."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import (
    PortaleConsumiApi,
    PortaleConsumiAuthError,
    async_build_ssl_context,
    create_session,
    PortaleConsumiError,
    PortaleConsumiSessionSuspect,
)
from .const import (
    CONF_COOKIE_HEADER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
    NAME,
)


_LOGGER = logging.getLogger(__name__)


def _interval_validator():
    return vol.All(
        vol.Coerce(int),
        vol.Range(min=MIN_SCAN_INTERVAL_HOURS, max=MAX_SCAN_INTERVAL_HOURS),
    )


def _user_schema(default_interval: int = DEFAULT_SCAN_INTERVAL_HOURS) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_COOKIE_HEADER): str,
            vol.Required(
                CONF_SCAN_INTERVAL_HOURS,
                default=default_interval,
            ): _interval_validator(),
        }
    )


def _cookie_schema() -> vol.Schema:
    return vol.Schema({vol.Required(CONF_COOKIE_HEADER): str})


async def _validate_input(
    hass: HomeAssistant,
    user_input: dict,
) -> str | None:
    """Verifica la sessione con una richiesta al servizio forniture."""
    ssl_context = await async_build_ssl_context(hass)
    async with create_session(ssl_context, total_timeout=30) as session:
        try:
            api = PortaleConsumiApi(session, user_input[CONF_COOKIE_HEADER])
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

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            error = await _validate_input(self.hass, user_input)
            if error is None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_COOKIE_HEADER: user_input[CONF_COOKIE_HEADER]},
                    options={
                        CONF_SCAN_INTERVAL_HOURS: user_input[
                            CONF_SCAN_INTERVAL_HOURS
                        ]
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    # --- Rinnovo della sessione (cookie) -----------------------------------

    async def async_step_reauth(self, entry_data):
        """Avviato da Home Assistant quando il portale rifiuta la sessione."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            error = await _validate_input(self.hass, user_input)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_COOKIE_HEADER: user_input[CONF_COOKIE_HEADER]
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_cookie_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Permette di sostituire il cookie prima che scada."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            error = await _validate_input(self.hass, user_input)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_COOKIE_HEADER: user_input[CONF_COOKIE_HEADER]
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_cookie_schema(),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return ConsumiOptionsFlow()


class ConsumiOptionsFlow(config_entries.OptionsFlow):
    """Permette di cambiare l'intervallo di aggiornamento."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_SCAN_INTERVAL_HOURS: user_input[CONF_SCAN_INTERVAL_HOURS]},
            )

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_HOURS,
            DEFAULT_SCAN_INTERVAL_HOURS,
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_HOURS,
                        default=current_interval,
                    ): _interval_validator(),
                }
            ),
        )
