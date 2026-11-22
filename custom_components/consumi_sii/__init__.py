"""Integrazione Consumi luce e gas (SII)."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import async_build_ssl_context, create_session
from .const import CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
from .coordinator import ConsumiConfigEntry, ConsumiCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConsumiConfigEntry) -> bool:
    session = create_session(await async_build_ssl_context(hass))
    entry.async_on_unload(session.close)
    try:
        coordinator = ConsumiCoordinator(hass, entry, session)
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConsumiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ConsumiConfigEntry) -> None:
    """Ricarica solo se cambia l'intervallo.

    Il cookie rinnovato dal portale viene salvato dal coordinator e non deve
    ricaricare l'integrazione; un cookie nuovo inserito dall'utente passa da
    reauth/riconfigura, che ricaricano da sé.
    """
    interval = entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
    if interval != entry.runtime_data.interval_hours:
        hass.config_entries.async_schedule_reload(entry.entry_id)
