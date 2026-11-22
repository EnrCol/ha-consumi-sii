"""Invio dal browser: chiave, ricezione, decodifica e conversione dei dati."""
import gzip
import base64
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

browser = load("browser")

SAMPLE = {
    "v": 1,
    "fe": {"pod": [
        {"codice_pod": "IT001E1", "forniture": [{"data_inizio_fornitura": "20200101", "data_fine_fornitura": ""}]},
        {"codice_pod": "IT001E2", "forniture": [{"data_inizio_fornitura": "20100101", "data_fine_fornitura": "20150101"}]},
    ]},
    "fg": {},
    "ce": {"IT001E1": {"misure_mensili": [{"competenza_consumi": "202601", "delta_misure_f1": 10}]}},
    "cg": {},
}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class KeyTests(unittest.TestCase):
    def test_pending_flow_by_key_and_expiry(self):
        clock = Clock()
        pending = browser.PendingFlows(clock=clock)
        key = pending.create("a" * 26)
        self.assertRegex(key, browser.KEY_RE)
        self.assertTrue(pending.is_valid("a" * 26, key))
        self.assertFalse(pending.is_valid("b" * 26, key))
        self.assertIsNone(pending.flow_for("x" * 43))
        clock.now += browser.PENDING_TTL_SECONDS + 1
        self.assertIsNone(pending.flow_for(key))

    def test_new_key_replaces_previous_for_same_flow(self):
        pending = browser.PendingFlows(clock=Clock())
        first = pending.create("a" * 26)
        second = pending.create("a" * 26)
        self.assertIsNone(pending.flow_for(first))
        self.assertEqual(pending.flow_for(second), "a" * 26)

    def test_outcome_and_lock(self):
        clock = Clock()
        pending = browser.PendingFlows(clock=clock)
        key = pending.create("a" * 26)
        pending.set_outcome("a" * 26, "ok_setup")
        self.assertEqual(pending.pop(key), "ok_setup")
        for _ in range(browser.MAX_KEY_FAILURES):
            pending.record_failure()
        self.assertTrue(pending.locked())
        clock.now += browser.KEY_FAILURE_WINDOW_SECONDS + 1
        self.assertFalse(pending.locked())

    def test_hash_matches(self):
        key = browser.new_key()
        self.assertTrue(browser.hash_matches(browser.key_hash(key), key))
        self.assertFalse(browser.hash_matches(browser.key_hash(key), browser.new_key()))
        self.assertFalse(browser.hash_matches(None, key))


class ReceiveTests(unittest.TestCase):
    def test_body_shape(self):
        key = browser.new_key()
        good = json.dumps({"key": key, "payload": "zAbc_-"}).encode()
        self.assertEqual(browser.parse_receive_body(good), (key, "zAbc_-"))
        for bad in (b"", b"[]", b"{", json.dumps({"key": "short", "payload": "zA"}).encode(),
                    json.dumps({"key": key, "payload": "xA"}).encode()):
            with self.subTest(bad=bad):
                self.assertIsNone(browser.parse_receive_body(bad))

    def test_origin(self):
        self.assertTrue(browser.origin_allowed("http://ha.local:8123", "http", "ha.local:8123"))
        self.assertTrue(browser.origin_allowed("https://ha.example", "https", "ha.example:443"))
        self.assertFalse(browser.origin_allowed("https://www.consumienergia.it", "http", "ha.local:8123"))
        self.assertFalse(browser.origin_allowed(None, "http", "ha.local:8123"))
        self.assertFalse(browser.origin_allowed("null", "http", "ha.local:8123"))


class PayloadTests(unittest.TestCase):
    def test_round_trip_and_active_points_only(self):
        data = browser.decode_payload(browser.encode_payload_for_tests(SAMPLE))
        series = browser.extract_series(data, date(2026, 11, 22))
        self.assertEqual(browser.series_to_store(series), {"luce|IT001E1": {"202601": 10.0}})

    def test_plain_json_variant(self):
        raw = base64.urlsafe_b64encode(json.dumps(SAMPLE).encode()).decode().rstrip("=")
        self.assertEqual(browser.decode_payload("j" + raw)["v"], 1)

    def test_rejects_bad_payloads(self):
        bomb = gzip.compress(b"{" + b" " * (browser.MAX_DECOMPRESSED_BYTES + 10) + b"}")
        bad = [
            "zNOTGZIP",
            "j" + base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("="),
            "j" + base64.urlsafe_b64encode(json.dumps({"v": 2}).encode()).decode().rstrip("="),
            "z" + base64.urlsafe_b64encode(bomb).decode().rstrip("="),
        ]
        for payload in bad:
            with self.subTest(payload=payload[:12]), self.assertRaises(browser.PayloadError):
                browser.decode_payload(payload)

    def test_store_round_trip_ignores_garbage(self):
        stored = {"luce|IT1": {"202601": 1.5, "bad": 2, "202602": True}, "acqua|X": {}, "gas|": {}}
        series = browser.series_from_store(stored)
        self.assertEqual(list(series), [("luce", "IT1")])
        self.assertEqual(series[("luce", "IT1")].months, {"202601": 1.5})


class PageTests(unittest.TestCase):
    def test_start_page_has_no_key_in_markup(self):
        page = browser.start_page(True)
        self.assertIn(browser.BOOKMARK_NAME, page)
        self.assertIn("history.replaceState", page)
        self.assertNotIn("__KEY__\"", page.split("var tpl=")[0])

    def test_invalid_start_page(self):
        self.assertIn("scaduto", browser.start_page(False))


if __name__ == "__main__":
    unittest.main()
