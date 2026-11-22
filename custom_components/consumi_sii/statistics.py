"""Statistiche esterne mensili, utilizzabili nella dashboard Energia.

Ogni misura mensile del portale diventa una riga oraria posta alla
mezzanotte locale del primo giorno del mese. Nella vista mensile e annuale
della dashboard Energia il totale è corretto; nella vista giornaliera il
consumo appare tutto il giorno 1.
"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import ELECTRIC, PointSeries, cumulative_months, mask_code, statistic_id

_LOGGER = logging.getLogger(__name__)
_EPOCH = datetime(2000, 1, 1, tzinfo=dt_util.UTC)


def _month_start(year: int, month: int) -> datetime:
    return dt_util.as_utc(
        datetime(year, month, 1, tzinfo=dt_util.get_default_time_zone())
    )


async def _sum_before(hass: HomeAssistant, stat_id: str, before: datetime) -> float:
    """Somma già registrata prima della prima competenza importata.

    Se il portale smette di pubblicare i mesi più vecchi, la serie riparte
    da qui invece che da zero e la somma non torna indietro.
    """
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        _EPOCH,
        before,
        {stat_id},
        "hour",
        None,
        {"sum"},
    )
    series = rows.get(stat_id) or []
    if not series:
        return 0.0
    return float(series[-1].get("sum") or 0.0)


async def async_import_series(hass: HomeAssistant, series: PointSeries) -> None:
    """Scrive (o riscrive) tutta la serie mensile di un punto."""
    rows = cumulative_months(series)
    if not rows:
        return

    stat_id = statistic_id(DOMAIN, series.commodity, series.code)
    first_start = _month_start(rows[0][0], rows[0][1])
    try:
        offset = await _sum_before(hass, stat_id, first_start)
    except Exception:  # noqa: BLE001 - il recorder non deve bloccare i sensori
        _LOGGER.warning("Impossibile leggere le statistiche esistenti di %s", stat_id)
        return

    electric = series.commodity == ELECTRIC
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=f"{'Luce' if electric else 'Gas'} {mask_code(series.code)} (SII)",
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class="energy" if electric else "volume",
        unit_of_measurement=(
            UnitOfEnergy.KILO_WATT_HOUR if electric else UnitOfVolume.CUBIC_METERS
        ),
    )
    statistics = [
        StatisticData(
            start=_month_start(year, month),
            state=value,
            sum=round(offset + total, 3),
        )
        for year, month, value, total in rows
    ]
    async_add_external_statistics(hass, metadata, statistics)
    _LOGGER.debug("Importate %d righe mensili in %s", len(statistics), stat_id)
