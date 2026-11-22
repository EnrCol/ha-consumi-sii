"""Dati dei consumi: inviati dal preferito oppure letti con il cookie."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PortaleConsumiApi,
    PortaleConsumiAuthError,
    PortaleConsumiError,
    PortaleConsumiSessionSuspect,
)
from .browser import series_from_store, series_to_store
from .const import (
    CONF_COOKIE_HEADER,
    CONF_MODE,
    CONF_RECEIVED_AT,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SERIES,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    KEEPALIVE_MINUTES,
    MODE_BROWSER,
    STALE_DAYS,
)
from .models import ELECTRIC, GAS, PointSeries, ResponseShapeError, active_point_codes, build_series
from .statistics import async_import_series

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumiData:
    """Risultato di un aggiornamento."""

    points: dict[tuple[str, str], PointSeries]
    last_update: datetime | None


type ConsumiConfigEntry = ConfigEntry["ConsumiCoordinator"]


class ConsumiCoordinator(DataUpdateCoordinator[ConsumiData]):
    """Una voce di configurazione: modalità preferito o cookie."""

    config_entry: ConsumiConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConsumiConfigEntry,
        session: aiohttp.ClientSession | None,
    ) -> None:
        self.browser_mode = entry.data.get(CONF_MODE) == MODE_BROWSER
        self.interval_hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            # Modalità preferito: nessun polling, i dati arrivano dal browser.
            update_interval=None if self.browser_mode else timedelta(hours=self.interval_hours),
        )
        self.session = session
        self.api = (
            None
            if self.browser_mode or session is None
            else PortaleConsumiApi(session, entry.data[CONF_COOKIE_HEADER])
        )
        self._statistics_imported = False
        # URL assoluto della pagina «Aggiorna consumi» (impostato da __init__).
        self.update_page_url: str | None = None

    # ----------------------------------------------------------- promemoria
    @property
    def _stale_issue_id(self) -> str:
        return f"dati_vecchi_{self.config_entry.entry_id}"

    @callback
    def async_check_stale(self, _now: datetime | None = None) -> None:
        """Avviso in Riparazioni quando i dati del preferito hanno più di STALE_DAYS giorni."""
        last = self.data.last_update if self.data else None
        days = (dt_util.utcnow() - last).days if last else None
        if days is None or days < STALE_DAYS:
            ir.async_delete_issue(self.hass, DOMAIN, self._stale_issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._stale_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dati_vecchi",
            translation_placeholders={"giorni": str(days)},
            learn_more_url=self.update_page_url,
        )

    @callback
    def async_start_stale_check(self) -> None:
        if not self.browser_mode:
            return
        self.async_check_stale()
        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, self.async_check_stale, timedelta(hours=12))
        )
        self.config_entry.async_on_unload(
            lambda: ir.async_delete_issue(self.hass, DOMAIN, self._stale_issue_id)
        )

    # ----------------------------------------------------------- preferito
    def _stored_data(self) -> ConsumiData:
        received = self.config_entry.data.get(CONF_RECEIVED_AT)
        return ConsumiData(
            points=series_from_store(self.config_entry.data.get(CONF_SERIES)),
            last_update=dt_util.parse_datetime(received) if received else None,
        )

    async def async_apply_browser_series(
        self, series: dict[tuple[str, str], PointSeries]
    ) -> None:
        """Nuovi dati dal preferito: salva, importa le statistiche, aggiorna."""
        now = dt_util.utcnow()
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_SERIES: series_to_store(series),
                CONF_RECEIVED_AT: now.isoformat(),
            },
        )
        for item in series.values():
            await async_import_series(self.hass, item)
        self.async_set_updated_data(ConsumiData(points=series, last_update=now))
        self.async_check_stale()

    # ----------------------------------------------------------- cookie
    async def _fetch_with_cookie(self) -> ConsumiData:
        assert self.api is not None
        try:
            electric_supplies = await self.api.get_forniture_elettriche()
            gas_supplies = await self.api.get_forniture_gas()
            today = dt_util.now().date()
            points: dict[tuple[str, str], PointSeries] = {}
            for code in active_point_codes(electric_supplies, "pod", "codice_pod", today):
                payload = await self.api.get_consumi_elettrici(code)
                points[(ELECTRIC, code)] = build_series(ELECTRIC, code, payload)
            for code in active_point_codes(gas_supplies, "pdr", "codice_pdr", today):
                payload = await self.api.get_consumi_gas(code)
                points[(GAS, code)] = build_series(GAS, code, payload)
        except PortaleConsumiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PortaleConsumiSessionSuspect as err:
            # Il portale risponde così alle sessioni scadute; se la home
            # pubblica è su, il problema è la sessione.
            if await self.api.portal_is_up():
                raise ConfigEntryAuthFailed(
                    "Sessione del Portale Consumi scaduta: serve un nuovo accesso."
                ) from err
            raise UpdateFailed(str(err)) from err
        except (PortaleConsumiError, ResponseShapeError) as err:
            raise UpdateFailed(str(err)) from err
        finally:
            self._persist_renewed_cookie()
        return ConsumiData(points=points, last_update=dt_util.utcnow())

    @callback
    def async_start_keepalive(self) -> None:
        """Come il rinnovo del token in ha-contarina: una richiesta leggera ogni
        10 minuti tiene viva la sessione del portale fra un aggiornamento e l'altro."""
        if self.api is None:
            return
        self.config_entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_keepalive, timedelta(minutes=KEEPALIVE_MINUTES)
            )
        )

    async def _async_keepalive(self, _now: datetime) -> None:
        assert self.api is not None
        try:
            await self.api.get_forniture_elettriche()
        except (PortaleConsumiAuthError, PortaleConsumiSessionSuspect):
            if isinstance(self.last_exception, ConfigEntryAuthFailed):
                return
            if await self.api.portal_is_up():
                _LOGGER.info("Sessione del Portale Consumi scaduta: avvio la riautenticazione")
                self.config_entry.async_start_reauth(self.hass)
        except PortaleConsumiError as err:
            _LOGGER.debug("Mantenimento sessione non riuscito: %s", err)
        finally:
            self._persist_renewed_cookie()

    def _persist_renewed_cookie(self) -> None:
        """Salva l'header se il portale ha rinnovato la sessione (senza ricaricare)."""
        if self.api is None:
            return
        header = self.api.cookie_header
        if header != self.config_entry.data.get(CONF_COOKIE_HEADER):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_COOKIE_HEADER: header},
            )

    # ----------------------------------------------------------- comune
    async def _async_update_data(self) -> ConsumiData:
        data = self._stored_data() if self.browser_mode else await self._fetch_with_cookie()
        if not self.browser_mode or not self._statistics_imported:
            for series in data.points.values():
                await async_import_series(self.hass, series)
            self._statistics_imported = True
        return data
