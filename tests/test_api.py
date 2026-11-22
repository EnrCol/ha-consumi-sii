"""Gestione del cookie: parsing, unione dei Set-Cookie, nessun segreto nei test."""
import sys
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

api = load("api")


class CookieTests(unittest.TestCase):
    def test_parse_accepts_full_devtools_line(self):
        self.assertEqual(
            api.parse_cookie_header("Cookie: A=1; B=x=y ;  ; C="),
            {"A": "1", "B": "x=y", "C": ""},
        )

    def test_round_trip(self):
        header = "JSESSIONID=abc; other=1"
        self.assertEqual(api.format_cookie_header(api.parse_cookie_header(header)), header)

    def test_merge_updates_adds_and_deletes(self):
        cookies = {"JSESSIONID": "old", "keep": "1", "gone": "x"}
        received = SimpleCookie()
        received.load("JSESSIONID=new; Path=/")
        received.load("fresh=2")
        received.load("gone=deleted; Max-Age=0")
        self.assertTrue(api.merge_set_cookies(cookies, received))
        self.assertEqual(cookies, {"JSESSIONID": "new", "keep": "1", "fresh": "2"})

    def test_merge_without_changes(self):
        cookies = {"A": "1"}
        received = SimpleCookie()
        received.load("A=1")
        self.assertFalse(api.merge_set_cookies(cookies, received))

    def test_empty_header_rejected(self):
        with self.assertRaises(api.PortaleConsumiAuthError):
            api.PortaleConsumiApi(None, "  ")

    def test_unwrap_result_decodes_string(self):
        self.assertEqual(api.unwrap_result({"response": {"result": "{\"a\": 1}"}}), {"a": 1})
        with self.assertRaises(api.PortaleConsumiError):
            api.unwrap_result({"response": {}})

    def test_invalid_session_error_code(self):
        body = {"response": {"errors": {"error": {"code": "API_INVALID_RESPONSE",
                "message": "Invalid or null Response"}}, "result": "FAILURE"}}
        self.assertEqual(api._error_code(body), "API_INVALID_RESPONSE")
        self.assertIsNone(api._error_code({"response": {"result": "ok"}}))
        self.assertIsNone(api._error_code(None))
        self.assertTrue(issubclass(api.PortaleConsumiSessionSuspect, api.PortaleConsumiError))


if __name__ == "__main__":
    unittest.main()
