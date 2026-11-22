"""Integrazione Consumi luce e gas (SII)."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api import async_build_ssl_context, create_session
from .browser_views import async_register_views
from .const import (
    CONF_MODE,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MODE_BROWSER,
)
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
    _async_migrate_registry(hass, entry)
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


@callback
def _async_migrate_registry(hass: HomeAssistant, entry: ConsumiConfigEntry) -> None:
    """Allinea il registro alle versioni precedenti (fino a 0.4.0b5).

    - Il dispositivo di servizio con «Ultimo aggiornamento» non esiste più:
      il sensore ora sta sul dispositivo di ogni POD/PDR.
    - I mesi erano disattivati di default: si riattivano solo quelli
      disattivati dall'integrazione, mai quelli spenti dall'utente.
    """
    ent_reg = er.async_get(hass)
    old_unique_id = f"{entry.entry_id}_ultimo_aggiornamento"
    if old_entity := ent_reg.async_get_entity_id("sensor", DOMAIN, old_unique_id):
        ent_reg.async_remove(old_entity)
    dev_reg = dr.async_get(hass)
    if old_device := dev_reg.async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id):
        dev_reg.async_remove_device(old_device.id)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            ent_reg.async_update_entity(entity.entity_id, disabled_by=None)
