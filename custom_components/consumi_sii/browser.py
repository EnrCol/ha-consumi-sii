"""Invio dei consumi dal browser: chiave, preferito, pagine statiche, decodifica.

Python puro (nessun import di Home Assistant): coperto dai test in ``tests/``.

Perché non si trasferisce il cookie come in ha-contarina: il cookie di sessione
del portale (``JSESSIONID``) è ``HttpOnly`` e un preferito non può leggerlo.
Il preferito però gira nella pagina del portale, dove il browser allega da sé
quel cookie: legge i quattro servizi JSON e invia ad Home Assistant **i dati**,
non la credenziale. Home Assistant non conserva nulla che possa scadere.

Modello di sicurezza:
- la chiave di invio (256 bit) nasce nel config flow, avviato da un utente HA
  autenticato, e arriva solo al suo browser nella pagina di avvio;
- il preferito contiene l'indirizzo di HA e la chiave; HA conserva solo
  l'hash SHA-256 della chiave;
- la chiave autorizza soltanto a sostituire i consumi di questa voce: non legge
  nulla, non comanda nulla; si cambia con «Riconfigura»;
- i dati viaggiano nel frammento dell'URL (mai inviato in rete), poi la pagina
  di ricezione li spedisce con una POST same-origin; tentativi con chiavi
  sbagliate bloccano temporaneamente la ricezione.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import hmac
import json
import re
import secrets
import time
import zlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable
from urllib.parse import urlsplit

from .models import ELECTRIC, GAS, PointSeries, active_point_codes, build_series

PENDING_TTL_SECONDS = 1800  # login SPID compreso
MAX_KEY_FAILURES = 20
KEY_FAILURE_WINDOW_SECONDS = 600
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 20 * 1024 * 1024

BASE_PATH = "/api/consumi_sii/browser"
START_PATH = f"{BASE_PATH}/start"
RECEIVE_PATH = f"{BASE_PATH}/receive"
PORTAL_HOST = "www.consumienergia.it"
PORTAL_URL = f"https://{PORTAL_HOST}/portaleConsumi/"

FLOW_ID_RE = re.compile(r"[A-Za-z0-9]{16,64}")
KEY_RE = re.compile(r"[A-Za-z0-9_-]{43}")
PAYLOAD_RE = re.compile(r"[zj][A-Za-z0-9_-]+")

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


class PayloadError(ValueError):
    """Dati inviati dal preferito non validi."""


def new_key() -> str:
    return secrets.token_urlsafe(32)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def hash_matches(stored: str | None, key: str) -> bool:
    return bool(stored) and hmac.compare_digest(stored, key_hash(key))


@dataclass
class _Pending:
    flow_id: str
    expires: float
    outcome: str | None = None


@dataclass
class PendingFlows:
    """Config flow in attesa dei dati, per hash della chiave. In memoria."""

    clock: Callable[[], float] = time.monotonic
    _items: dict[str, _Pending] = field(default_factory=dict)
    _failures: list[float] = field(default_factory=list)

    def _purge(self) -> None:
        now = self.clock()
        for h in [h for h, item in self._items.items() if item.expires <= now]:
            del self._items[h]

    def create(self, flow_id: str) -> str:
        if not FLOW_ID_RE.fullmatch(flow_id):
            raise ValueError("invalid flow id")
        self._purge()
        for h in [h for h, item in self._items.items() if item.flow_id == flow_id]:
            del self._items[h]
        key = new_key()
        self._items[key_hash(key)] = _Pending(flow_id, self.clock() + PENDING_TTL_SECONDS)
        return key

    def flow_for(self, key: str) -> str | None:
        self._purge()
        if not KEY_RE.fullmatch(key or ""):
            return None
        item = self._items.get(key_hash(key))
        return item.flow_id if item else None

    def is_valid(self, flow_id: str, key: str) -> bool:
        return self.flow_for(key) == flow_id

    def set_outcome(self, flow_id: str, outcome: str) -> None:
        for item in self._items.values():
            if item.flow_id == flow_id:
                item.outcome = outcome

    def pop(self, key: str) -> str | None:
        """Rimuove l'attesa e restituisce l'esito registrato dal flow."""
        item = self._items.pop(key_hash(key), None)
        return item.outcome if item else None

    def discard_flow(self, flow_id: str) -> None:
        for h in [h for h, item in self._items.items() if item.flow_id == flow_id]:
            del self._items[h]

    def locked(self) -> bool:
        now = self.clock()
        self._failures = [t for t in self._failures if now - t < KEY_FAILURE_WINDOW_SECONDS]
        return len(self._failures) >= MAX_KEY_FAILURES

    def record_failure(self) -> None:
        self._failures.append(self.clock())


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_tuple(scheme: str, netloc: str) -> tuple[str, str, int] | None:
    scheme = (scheme or "").lower()
    if scheme not in _DEFAULT_PORTS or not netloc or re.search(r"[/?#@\s]", netloc):
        return None
    try:
        parts = urlsplit(f"{scheme}://{netloc}")
        hostname, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not hostname:
        return None
    return scheme, hostname.lower().rstrip("."), port if port is not None else _DEFAULT_PORTS[scheme]


def origin_allowed(origin: str | None, request_scheme: str, request_host: str) -> bool:
    """Same-origin stretto (schema, host, porta) per la POST di ricezione."""
    if not origin or origin == "null":
        return False
    m = re.fullmatch(r"(https?)://([^/?#@\s]+)", origin.strip(), flags=re.IGNORECASE)
    if not m:
        return False
    got = _origin_tuple(m.group(1), m.group(2))
    return got is not None and got == _origin_tuple(request_scheme, request_host)


def parse_receive_body(raw: bytes) -> tuple[str, str] | None:
    """``{"key": ..., "payload": ...}`` → (chiave, payload). Mai rispecchiato."""
    if not raw or len(raw) > MAX_BODY_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    key, payload = data.get("key"), data.get("payload")
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        return None
    if not isinstance(payload, str) or not PAYLOAD_RE.fullmatch(payload):
        return None
    return key, payload


def _b64url_decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as err:
        raise PayloadError("codifica non valida") from err


def decode_payload(payload: str) -> dict[str, Any]:
    """``z`` + gzip in base64url, oppure ``j`` + JSON in base64url."""
    if not PAYLOAD_RE.fullmatch(payload or ""):
        raise PayloadError("formato non valido")
    raw = _b64url_decode(payload[1:])
    if payload[0] == "z":
        decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            raw = decomp.decompress(raw, MAX_DECOMPRESSED_BYTES)
        except zlib.error as err:
            raise PayloadError("compressione non valida") from err
        if decomp.unconsumed_tail:
            raise PayloadError("dati troppo grandi")
    elif len(raw) > MAX_DECOMPRESSED_BYTES:
        raise PayloadError("dati troppo grandi")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as err:
        raise PayloadError("JSON non valido") from err
    if not isinstance(data, dict) or data.get("v") != 1:
        raise PayloadError("versione dei dati non supportata")
    return data


def encode_payload_for_tests(data: dict[str, Any]) -> str:
    """Stessa codifica del preferito (``z`` + gzip), per i test."""
    raw = gzip.compress(json.dumps(data).encode())
    return "z" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def extract_series(data: dict[str, Any], today: date) -> dict[tuple[str, str], PointSeries]:
    """Dai dati del preferito alle serie mensili dei punti attivi."""
    electric = active_point_codes(data.get("fe"), "pod", "codice_pod", today)
    gas = active_point_codes(data.get("fg"), "pdr", "codice_pdr", today)
    consumi_e = data.get("ce") if isinstance(data.get("ce"), dict) else {}
    consumi_g = data.get("cg") if isinstance(data.get("cg"), dict) else {}
    series: dict[tuple[str, str], PointSeries] = {}
    for code in electric:
        series[(ELECTRIC, code)] = build_series(ELECTRIC, code, consumi_e.get(code))
    for code in gas:
        series[(GAS, code)] = build_series(GAS, code, consumi_g.get(code))
    return series


def series_to_store(series: dict[tuple[str, str], PointSeries]) -> dict[str, dict[str, float]]:
    return {f"{c}|{code}": dict(s.months) for (c, code), s in series.items()}


def series_from_store(stored: Any) -> dict[tuple[str, str], PointSeries]:
    result: dict[tuple[str, str], PointSeries] = {}
    if not isinstance(stored, dict):
        return result
    for name, months in stored.items():
        commodity, _, code = str(name).partition("|")
        if commodity not in (ELECTRIC, GAS) or not code or not isinstance(months, dict):
            continue
        clean = {
            str(k): float(v)
            for k, v in months.items()
            if re.fullmatch(r"\d{6}", str(k)) and isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        result[(commodity, code)] = PointSeries(commodity, code, dict(sorted(clean.items())))
    return result


# Preferito: gira sulla pagina autenticata del portale. __HA_ORIGIN__ e __KEY__
# vengono sostituiti nella pagina di avvio. Restituisce undefined (void), così
# il browser non sostituisce la pagina con il risultato.
BOOKMARKLET_TEMPLATE = (
    "void((async function(){"
    "var ha=__HA_ORIGIN__,key=__KEY__;"
    f"if(location.protocol!=='https:'||location.hostname!=='{PORTAL_HOST}')"
    "{alert('Apri prima il Portale Consumi ed entra con SPID o CIE.');return;}"
    "var box=document.createElement('div');"
    "box.style.cssText='position:fixed;top:12px;right:12px;z-index:2147483647;background:#1565c0;"
    "color:#fff;padding:12px 16px;border-radius:8px;font:15px system-ui,sans-serif;box-shadow:0 2px 8px #0005';"
    "box.textContent='Lettura dei consumi…';document.body.appendChild(box);"
    "var B='/portaleConsumi/legacyapi/rs/it/';"
    "async function get(ep,q){"
    "var r=await fetch(B+ep+'?'+new URLSearchParams(q),{credentials:'include',headers:{Accept:'application/json'}});"
    "var j;try{j=JSON.parse(await r.text());}catch(e){throw new Error('auth');}"
    "if(r.status===503||r.status===401||r.status===403)throw new Error('auth');"
    "if(!r.ok)throw new Error(ep+': HTTP '+r.status);"
    "var x=j&&j.response&&j.response.result;"
    # Il portale risponde result:"" quando non ci sono dati (es. nessuna fornitura gas).
    "if(typeof x==='string'){if(!x.trim())return {};"
    "try{x=JSON.parse(x);}catch(e){throw new Error(ep+': risposta non leggibile');}}"
    "if(x==null)throw new Error('auth');return x;}"
    "var Q={cf_delega:'null',denominazione_delegato:'undefined'};"
    "var d={v:1,ce:{},cg:{}};"
    "try{"
    "d.fe=await get('fornitureElettricheService.json',Q);"
    "d.fg=await get('fornitureGasService.json',Q);"
    "var i,p;"
    "var pods=(d.fe&&d.fe.pod)||[];"
    "for(i=0;i<pods.length;i++){p=pods[i]&&pods[i].codice_pod;"
    "if(p){box.textContent='Luce '+(i+1)+'/'+pods.length+'…';"
    "d.ce[p]=await get('consumiElettricoService.json',{code:p});}}"
    "var pdrs=(d.fg&&d.fg.pdr)||[];"
    "for(i=0;i<pdrs.length;i++){p=pdrs[i]&&pdrs[i].codice_pdr;"
    "if(p){box.textContent='Gas '+(i+1)+'/'+pdrs.length+'…';"
    "d.cg[p]=await get('consumiGasService.json',{code:p});}}"
    "}catch(e){box.remove();"
    "alert(e.message==='auth'?'Accesso al portale non rilevato: entra con SPID o CIE, apri le tue forniture e riprova.'"
    ":'Lettura dei consumi non riuscita: '+e.message);return;}"
    "box.textContent='Invio a Home Assistant…';"
    # Solo ciò che serve alle serie mensili: le curve orarie/quartorarie
    # (misure_altre_frequenze) possono pesare diversi MB.
    "function R(m){var n={},k;for(k in m)if(/^(competenza_consumi|data_lettura|tipo_misura|delta_misure)/.test(k))n[k]=m[k];return n;}"
    "function T(o){if(Array.isArray(o))return o.map(T);if(!o||typeof o!=='object')return o;"
    "var n={},k,M=Array.isArray(o.misure_mensili);for(k in o){"
    "if(k==='misure_altre_frequenze'&&M)continue;"
    "n[k]=(k==='misure_mensili'||k==='misure_altre_frequenze')&&Array.isArray(o[k])"
    "?o[k].filter(function(m){return m&&typeof m==='object';}).map(R):T(o[k]);}return n;}"
    "d.ce=T(d.ce);d.cg=T(d.cg);"
    "var s=JSON.stringify(d),bytes,pre;"
    "if(window.CompressionStream){"
    "bytes=new Uint8Array(await new Response(new Blob([s]).stream()"
    ".pipeThrough(new CompressionStream('gzip'))).arrayBuffer());pre='z';}"
    "else{bytes=new TextEncoder().encode(s);pre='j';}"
    "var bin='';for(i=0;i<bytes.length;i+=32768){"
    "bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+32768));}"
    "var b64=btoa(bin).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');"
    f"location.href=ha+'{RECEIVE_PATH}#'+key+'.'+pre+b64;"
    "})())"
)

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5;color:#222}a.bm{display:inline-block;padding:.5rem 1rem;border:2px dashed #1565c0;"
    "border-radius:8px;text-decoration:none;font-weight:600}a.go{display:inline-block;padding:.6rem 1.2rem;"
    "background:#1565c0;color:#fff;border-radius:8px;text-decoration:none}.err{color:#b00020}"
    ".ok{color:#2e7d32}button{font:inherit;padding:.4rem .8rem;border-radius:8px;border:1px solid #1565c0;"
    "background:#fff}li{margin-bottom:.6rem}"
)

BOOKMARK_NAME = "Invia consumi a Home Assistant"


def start_page(valid: bool) -> str:
    if not valid:
        return _page(
            "Consumi luce e gas",
            "<p class='err'>Collegamento scaduto o non valido. Riavvia la procedura da Home Assistant.</p>",
            "",
        )
    body = f"""
<h2>Collega i consumi di luce e gas</h2>
<ol>
<li>Crea il preferito <b>{BOOKMARK_NAME}</b>:
<ul>
<li><b>Computer</b>: trascina questo pulsante nella barra dei preferiti (non cliccarlo qui):
<a class="bm" id="bm" href="#">{BOOKMARK_NAME}</a></li>
<li><b>Smartphone</b>: <button id="copy" type="button">Copia codice del preferito</button>
<details><summary>Come crearlo sul telefono</summary>
<p>Aggiungi ai preferiti una pagina qualsiasi, poi modifica il preferito: incolla il codice copiato
al posto dell'indirizzo e chiamalo «{BOOKMARK_NAME}». Su Chrome Android, per usarlo scrivi
«Invia consumi» nella barra degli indirizzi mentre sei sul portale e tocca il preferito.</p>
</details></li>
</ul></li>
<li>Apri il Portale Consumi ed entra con <b>SPID o CIE</b>.</li>
<li>Quando vedi le tue forniture, usa il preferito: legge i consumi e torna qui da solo.</li>
</ol>
<p><a class="go" href="{PORTAL_URL}" rel="noreferrer" target="_self">Apri il Portale Consumi</a></p>
<p><small>Tieni il preferito: per aggiornare i dati basterà entrare nel portale e usarlo di nuovo,
senza passare da Home Assistant. Il preferito contiene l'indirizzo di questo Home Assistant e una
chiave che permette solo di inviare i consumi: non condividerlo. Se cambi l'indirizzo di Home
Assistant o vuoi cambiare chiave, usa «Riconfigura» nell'integrazione.</small></p>
"""
    script = f"""
(function(){{
  var q=new URLSearchParams(location.search), key=q.get('key')||'';
  history.replaceState(null,'',location.pathname);
  var tpl={json.dumps(BOOKMARKLET_TEMPLATE)};
  var code='javascript:'+encodeURIComponent(tpl.replace('__HA_ORIGIN__',JSON.stringify(location.origin)).replace('__KEY__',JSON.stringify(key)));
  var bm=document.getElementById('bm');
  bm.setAttribute('href',code);
  bm.addEventListener('click',function(ev){{ev.preventDefault();alert('Trascina il pulsante nella barra dei preferiti.');}});
  document.getElementById('copy').addEventListener('click',function(){{
    var done=function(){{document.getElementById('copy').textContent='Codice copiato';}};
    if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(code).then(done,function(){{prompt('Copia il codice del preferito:',code);}});}}
    else{{prompt('Copia il codice del preferito:',code);}}
  }});
}})();
"""
    return _page("Collega i consumi di luce e gas", body, script)


def receive_page() -> str:
    body = "<h2>Consumi luce e gas</h2><p id='msg'>Invio dei consumi a Home Assistant…</p>"
    script = f"""
(function(){{
  var msg=document.getElementById('msg');
  function show(t,c){{msg.textContent=t;msg.className=c||'';}}
  var h=location.hash.slice(1), dot=h.indexOf('.');
  history.replaceState(null,'',location.pathname);
  if(dot<1){{show('Nessun dato ricevuto. Usa il preferito sulla pagina del Portale Consumi dopo l\\'accesso.','err');return;}}
  fetch({json.dumps(RECEIVE_PATH)},{{method:'POST',credentials:'same-origin',referrerPolicy:'no-referrer',cache:'no-store',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key:h.slice(0,dot),payload:h.slice(dot+1)}})}})
  .then(function(r){{return r.json().catch(function(){{return {{}};}}).then(function(j){{return [r.status,j];}});}})
  .then(function(x){{show(x[1].message||(x[0]===200?'Fatto.':'Invio non riuscito.'),x[0]===200?'ok':'err');}})
  .catch(function(){{show('Home Assistant non raggiungibile da questo browser.','err');}});
}})();
"""
    return _page("Consumi luce e gas", body, script)


def _page(title: str, body: str, script: str) -> str:
    return (
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='referrer' content='no-referrer'>"
        f"<title>{title}</title><style>{_STYLE}</style></head><body>{body}"
        f"<script>{script}</script></body></html>"
    )


OUTCOME_MESSAGES = {
    "ok_setup": "Consumi ricevuti. Torna a Home Assistant per completare la configurazione.",
    "ok_update": "Consumi aggiornati in Home Assistant. Puoi chiudere questa scheda.",
    "no_points": "Il portale non mostra forniture attive di luce o gas per questo accesso.",
    "bad_key": "Preferito non riconosciuto da questo Home Assistant: ricrealo da «Riconfigura».",
    "locked": "Troppi tentativi non validi: attendi qualche minuto e riprova.",
    "bad_data": "I dati ricevuti non sono validi. Riprova dalla pagina delle forniture.",
    "expired": "Collegamento scaduto: riavvia la procedura da Home Assistant.",
    "forbidden_origin": "Richiesta non proveniente da questo Home Assistant.",
    "bad_request": "Richiesta non valida.",
    "too_large": "Dati troppo grandi per l'invio: segnala il problema su GitHub.",
}
