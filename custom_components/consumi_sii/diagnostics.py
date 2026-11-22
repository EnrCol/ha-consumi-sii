"""Diagnostica senza cookie né codici completi."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_COOKIE_HEADER
from .coordinator import ConsumiConfigEntry
from .models import mask_code


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConsumiConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "options": dict(entry.options),
        "cookie": {
            "presente": bool(entry.data.get(CONF_COOKIE_HEADER)),
            "nomi": sorted(coordinator.api._cookies),  # noqa: SLF001 - solo i nomi
        },
        "ultimo_aggiornamento": data.last_update.isoformat() if data else None,
        "punti": [
            {
                "tipo": series.commodity,
                "codice": mask_code(series.code),
                "mesi": len(series.months),
                "prima_competenza": min(series.months) if series.months else None,
                "ultima_competenza": max(series.months) if series.months else None,
            }
            for series in (data.points.values() if data else [])
        ],
    }
