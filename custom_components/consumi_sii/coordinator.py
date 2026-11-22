"""Aggiornamento periodico: punti attivi, serie mensili e statistiche."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PortaleConsumiApi,
    PortaleConsumiAuthError,
    PortaleConsumiError,
    PortaleConsumiSessionSuspect,
)
from .const import (
    CONF_COOKIE_HEADER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .models import ELECTRIC, GAS, PointSeries, ResponseShapeError, active_point_codes, build_series
from .statistics import async_import_series

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumiData:
    """Risultato di un aggiornamento."""

    points: dict[tuple[str, str], PointSeries]
    last_update: datetime


type ConsumiConfigEntry = ConfigEntry["ConsumiCoordinator"]


class ConsumiCoordinator(DataUpdateCoordinator[ConsumiData]):
    """Recupera i punti attivi e tutte le misure, anche di gestori cessati."""

    config_entry: ConsumiConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConsumiConfigEntry,
        session: aiohttp.ClientSession,
    ) -> None:
        self.interval_hours = entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=self.interval_hours),
        )
        self.session = session
        self.api = PortaleConsumiApi(session, entry.data[CONF_COOKIE_HEADER])

    async def _async_update_data(self) -> ConsumiData:
        try:
            electric_supplies = await self.api.get_forniture_elettriche()
            gas_supplies = await self.api.get_forniture_gas()
            today = dt_util.now().date()
            electric_codes = active_point_codes(electric_supplies, "pod", "codice_pod", today)
            gas_codes = active_point_codes(gas_supplies, "pdr", "codice_pdr", today)

            # Una chiamata per punto: restituisce anche le misure dei
            # precedenti gestori.
            points: dict[tuple[str, str], PointSeries] = {}
            for code in electric_codes:
                payload = await self.api.get_consumi_elettrici(code)
                points[(ELECTRIC, code)] = build_series(ELECTRIC, code, payload)
            for code in gas_codes:
                payload = await self.api.get_consumi_gas(code)
                points[(GAS, code)] = build_series(GAS, code, payload)
        except PortaleConsumiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PortaleConsumiSessionSuspect as err:
            # Il portale risponde così alle sessioni scadute; se la home
            # pubblica è su, il problema è la sessione e serve un cookie nuovo.
            if await self.api.portal_is_up():
                raise ConfigEntryAuthFailed(
                    "Sessione del Portale Consumi scaduta: serve un cookie nuovo."
                ) from err
            raise UpdateFailed(str(err)) from err
        except (PortaleConsumiError, ResponseShapeError) as err:
            raise UpdateFailed(str(err)) from err
        finally:
            self._persist_renewed_cookie()

        for series in points.values():
            await async_import_series(self.hass, series)

        return ConsumiData(points=points, last_update=dt_util.utcnow())

    def _persist_renewed_cookie(self) -> None:
        """Salva l'header se il portale ha rinnovato la sessione.

        Il listener di aggiornamento in ``__init__`` ignora questo cambio,
        quindi non provoca un ricaricamento.
        """
        header = self.api.cookie_header
        if header != self.config_entry.data.get(CONF_COOKIE_HEADER):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_COOKIE_HEADER: header},
            )
