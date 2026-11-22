"""Pagine HTTP dell'invio dal browser (pagina di avvio e ricezione)."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers.network import is_cloud_connection
from homeassistant.util import dt as dt_util

from .browser import (
    MAX_BODY_BYTES,
    OUTCOME_MESSAGES,
    RECEIVE_PATH,
    SECURITY_HEADERS,
    START_PATH,
    PayloadError,
    PendingFlows,
    decode_payload,
    extract_series,
    hash_matches,
    origin_allowed,
    parse_receive_body,
    receive_page,
    series_to_store,
    start_page,
)
from .const import CONF_KEY_HASH, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_PENDING = f"{DOMAIN}_browser_pending"
DATA_VIEWS = f"{DOMAIN}_browser_views"
FLOW_SERIES = "series"


@callback
def get_pending(hass: HomeAssistant) -> PendingFlows:
    pending = hass.data.get(DATA_PENDING)
    if pending is None:
        pending = hass.data[DATA_PENDING] = PendingFlows()
    return pending


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Idempotente: le pagine si registrano una volta per avvio di HA."""
    if hass.data.get(DATA_VIEWS):
        return
    hass.data[DATA_VIEWS] = True
    get_pending(hass)
    hass.http.register_view(BrowserStartView())
    hass.http.register_view(BrowserReceiveView())


def _html(text: str, status: int = 200) -> web.Response:
    return web.Response(
        text=text, status=status, content_type="text/html", charset="utf-8", headers=SECURITY_HEADERS
    )


def _json(result: str, status: int) -> web.Response:
    return web.json_response(
        {"result": result, "message": OUTCOME_MESSAGES.get(result, "Invio non riuscito.")},
        status=status,
        headers={k: v for k, v in SECURITY_HEADERS.items() if k != "Content-Security-Policy"},
    )


class BrowserStartView(HomeAssistantView):
    """Aperta dal frontend nell'external step; autorizzata dalla chiave del flow."""

    url = START_PATH
    name = f"api:{DOMAIN}:browser:start"
    requires_auth = False  # come il callback OAuth2 di HA: la chiave monouso è l'autorizzazione

    async def get(self, request: web.Request) -> web.Response:
        pending = get_pending(request.app[KEY_HASS])
        valid = pending.is_valid(request.query.get("flow_id", ""), request.query.get("key", ""))
        return _html(start_page(valid), 200 if valid else 410)


class BrowserReceiveView(HomeAssistantView):
    """GET: pagina che legge il frammento. POST: consegna same-origin."""

    url = RECEIVE_PATH
    name = f"api:{DOMAIN}:browser:receive"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        return _html(receive_page())

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        scheme = "https" if is_cloud_connection(hass) else request.scheme
        if not origin_allowed(request.headers.get("Origin"), scheme, request.host):
            return _json("forbidden_origin", 403)
        if request.content_type != "application/json":
            _LOGGER.warning("Invio dal preferito scartato: Content-Type %s", request.content_type)
            return _json("bad_request", 400)
        raw = await request.content.read(MAX_BODY_BYTES + 1)
        if (request.content_length or 0) > MAX_BODY_BYTES or len(raw) > MAX_BODY_BYTES:
            _LOGGER.warning(
                "Invio dal preferito scartato: %s byte, limite %s",
                request.content_length or len(raw), MAX_BODY_BYTES,
            )
            return _json("too_large", 413)
        parsed = parse_receive_body(raw)
        if parsed is None:
            _LOGGER.warning("Invio dal preferito scartato: corpo non valido (%s byte)", len(raw))
            return _json("bad_request", 400)
        key, payload = parsed

        pending = get_pending(hass)
        if pending.locked():
            return _json("locked", 429)

        flow_id = pending.flow_for(key)
        entry = None
        if flow_id is None:
            entry = next(
                (
                    e
                    for e in hass.config_entries.async_entries(DOMAIN)
                    if hash_matches(e.data.get(CONF_KEY_HASH), key)
                ),
                None,
            )
            if entry is None:
                pending.record_failure()
                return _json("locked" if pending.locked() else "bad_key", 403)

        try:
            data = await hass.async_add_executor_job(decode_payload, payload)
            series = extract_series(data, dt_util.now().date())
        except (PayloadError, ValueError) as err:
            _LOGGER.warning("Dati del preferito non validi: %s", err)
            return _json("bad_data", 400)
        if not series:
            return _json("no_points", 400)

        if flow_id is not None:
            try:
                await hass.config_entries.flow.async_configure(
                    flow_id, {FLOW_SERIES: series_to_store(series)}
                )
            except UnknownFlow:
                pending.discard_flow(flow_id)
                return _json("expired", 410)
            outcome = pending.pop(key) or "bad_data"
            return _json(outcome, 200 if outcome.startswith("ok") else 400)

        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is None:
            return _json("expired", 409)
        await coordinator.async_apply_browser_series(series)
        return _json("ok_update", 200)
