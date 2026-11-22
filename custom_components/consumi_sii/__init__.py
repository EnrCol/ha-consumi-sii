"""Integrazione Consumi luce e gas (SII)."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import async_build_ssl_context, create_session
from .browser_views import async_register_views
from .const import CONF_MODE, CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS, MODE_BROWSER
from .coordinator import ConsumiConfigEntry, ConsumiCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConsumiConfigEntry) -> bool:
    # Le pagine del preferito servono anche dopo un riavvio, per gli
    # aggiornamenti senza passare dal config flow.
    async_register_views(hass)

    session = None
    if entry.data.get(CONF_MODE) != MODE_BROWSER:
        session = create_session(await async_build_ssl_context(hass))
        entry.async_on_unload(session.close)
    try:
        coordinator = ConsumiCoordinator(hass, entry, session)
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        if session is not None:
            await session.close()
        raise

    entry.runtime_data = coordinator
    coordinator.async_start_keepalive()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConsumiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ConsumiConfigEntry) -> None:
    """Ricarica solo se cambia l'intervallo.

    Dati del preferito e cookie rinnovati vengono salvati dal coordinator e non
    devono ricaricare; riconfigura e reauth ricaricano da sé.
    """
    coordinator = entry.runtime_data
    interval = entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
    if not coordinator.browser_mode and interval != coordinator.interval_hours:
        hass.config_entries.async_schedule_reload(entry.entry_id)
