"""Integrazione Portale Consumi SII."""

from __future__ import annotations

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import async_build_ssl_context
from .const import DOMAIN
from .coordinator import PortaleConsumiCoordinator

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    ssl_context = await async_build_ssl_context(hass)
    # Il cookie jar è disattivato: il Cookie arriva solo dall'header inserito
    # dall'utente e i Set-Cookie del portale non vengono rispediti.
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=45),
        cookie_jar=aiohttp.DummyCookieJar(),
        connector=aiohttp.TCPConnector(ssl=ssl_context),
    )
    coordinator = PortaleConsumiCoordinator(hass, entry, session)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    hass.data[DOMAIN][entry.entry_id] = coordinator
    hass.data[DOMAIN][f"{entry.entry_id}_session"] = session
    # Ricarica l'integrazione quando cambiano opzioni o dati (intervallo, cookie).
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        session = hass.data[DOMAIN].pop(f"{entry.entry_id}_session", None)
        if session:
            await session.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
