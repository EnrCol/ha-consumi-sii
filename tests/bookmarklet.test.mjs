// Preferito "Invia consumi a Home Assistant" eseguito in una sandbox con un finto portale.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';
import vm from 'node:vm';

const root = new URL('..', import.meta.url).pathname;
const py = (code, input) => execFileSync('python3', ['-c', code], { cwd: root, input, encoding: 'utf8' });
const LOAD = "import sys; sys.path.insert(0,'tests'); from _load import load; b=load('browser');";
const template = py(`${LOAD} print(b.BOOKMARKLET_TEMPLATE)`).trim();
const RECEIVE = py(`${LOAD} print(b.RECEIVE_PATH)`).trim();
const KEY = 'A'.repeat(43);
const HA = 'http://ha.local:8123';
const source = template.replace('__HA_ORIGIN__', JSON.stringify(HA)).replace('__KEY__', JSON.stringify(KEY));

const wrap = (result) => JSON.stringify({ response: { result: JSON.stringify(result) } });
const PORTAL = {
  'fornitureElettricheService.json': [200, wrap({ pod: [{ codice_pod: 'IT001E00000001', forniture: [{ data_inizio_fornitura: '20200101', data_fine_fornitura: '' }] }] })],
  'fornitureGasService.json': [200, wrap({ pdr: [{ codice_pdr: '00881234567890', forniture: [{ data_inizio_fornitura: '20200101', data_fine_fornitura: '' }] }] })],
  'consumiElettricoService.json': [200, wrap({ misure_mensili: [{ competenza_consumi: '202509', delta_misure_f1: 100, delta_misure_f2: 50, data_lettura: '20251005' }] })],
  'consumiGasService.json': [200, wrap({ misure_mensili: [{ competenza_consumi: '202510', delta_misure: 42, data_lettura: '20251105' }] })],
};
const INVALID = [503, JSON.stringify({ response: { errors: { error: { code: 'API_INVALID_RESPONSE' } }, result: 'FAILURE' } })];

async function run({ host = 'www.consumienergia.it', responses = PORTAL, compression = true } = {}) {
  const alerts = [], requests = [];
  const location = { hostname: host, protocol: 'https:', href: `https://${host}/portaleConsumi/` };
  const body = { appendChild() {} };
  const window = { location, alert: (x) => alerts.push(x) };
  if (compression) window.CompressionStream = CompressionStream;
  const ctx = {
    window, location, alert: window.alert, URLSearchParams, JSON, String, Error, Blob, Response, TextEncoder, Uint8Array, btoa,
    CompressionStream: compression ? CompressionStream : undefined,
    document: { body, createElement: () => ({ style: {}, remove() {}, set textContent(v) {} }) },
    fetch: async (url, opts) => {
      requests.push({ url, opts });
      const ep = url.split('/').pop().split('?')[0];
      const [status, text] = responses[ep] || [404, '{}'];
      return { status, ok: status >= 200 && status < 300, text: async () => text };
    },
  };
  await vm.runInNewContext(source, ctx, { timeout: 5000 });
  for (let i = 0; i < 50 && location.href.startsWith('https://') && !alerts.length; i++) await new Promise((r) => setTimeout(r, 20));
  return { alerts, requests, href: location.href };
}

function decodeWithPython(href) {
  const [key, payload] = href.split('#')[1].split('.');
  const out = py(`${LOAD} import json,sys; from datetime import date; d=b.decode_payload(sys.stdin.read()); s=b.extract_series(d, date(2026,11,22)); print(json.dumps(b.series_to_store(s), sort_keys=True))`, payload);
  return { key, series: JSON.parse(out) };
}

test('il preferito è una espressione void: il browser non sostituisce la pagina', () => {
  assert.ok(template.startsWith('void((async function(){'));
  assert.ok(template.endsWith('})())'));
  assert.doesNotMatch(template, /document\.cookie/);
});

test('legge i quattro servizi con il cookie del browser e invia dati compressi', async () => {
  const { alerts, requests, href } = await run();
  assert.deepEqual(alerts, []);
  assert.equal(requests.length, 4);
  assert.ok(requests.every((r) => r.opts.credentials === 'include' && r.url.startsWith('/portaleConsumi/legacyapi/rs/it/')));
  assert.ok(href.startsWith(`${HA}${RECEIVE}#${KEY}.z`));
  const { key, series } = decodeWithPython(href);
  assert.equal(key, KEY);
  assert.deepEqual(series, { 'gas|00881234567890': { '202510': 42.0 }, 'luce|IT001E00000001': { '202509': 150.0 } });
});

test('senza CompressionStream invia JSON non compresso, decodificabile', async () => {
  const { href } = await run({ compression: false });
  assert.ok(href.includes(`#${KEY}.j`));
  assert.deepEqual(Object.keys(decodeWithPython(href).series).sort(), ['gas|00881234567890', 'luce|IT001E00000001']);
});

test('result vuoto (nessuna fornitura gas, punto senza misure) non blocca l\'invio', async () => {
  const empty = [200, JSON.stringify({ response: { result: '' } })];
  const { alerts, href } = await run({ responses: { ...PORTAL, 'fornitureGasService.json': empty, 'consumiElettricoService.json': empty } });
  assert.deepEqual(alerts, []);
  assert.deepEqual(decodeWithPython(href).series, { 'luce|IT001E00000001': {} });
});

test('risposta non leggibile: il messaggio dice quale servizio', async () => {
  const broken = [200, JSON.stringify({ response: { result: '{rotto' } })];
  const { alerts } = await run({ responses: { ...PORTAL, 'consumiGasService.json': broken } });
  assert.match(alerts[0], /consumiGasService\.json/);
});

test('fuori dal portale non legge nulla', async () => {
  const { alerts, requests } = await run({ host: 'example.org' });
  assert.equal(requests.length, 0);
  assert.match(alerts[0], /Portale Consumi/);
});

test('sessione non autenticata (503 API_INVALID_RESPONSE): chiede di entrare e non invia', async () => {
  const { alerts, href } = await run({ responses: { ...PORTAL, 'fornitureElettricheService.json': INVALID } });
  assert.match(alerts[0], /SPID o CIE/);
  assert.ok(!href.includes('#'));
});
