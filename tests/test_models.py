"""Test puri: nessuna installazione di Home Assistant né sessione SII."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

models = load("models")


def electric_record(competence, f1, f2=0, f3=0, data="20250101", tipo="Periodica"):
    return {
        "competenza_consumi": competence,
        "delta_misure_f1": f1,
        "delta_misure_f2": f2,
        "delta_misure_f3": f3,
        "data_lettura": data,
        "tipo_misura": tipo,
    }


class ActivePointsTests(unittest.TestCase):
    def test_open_and_future_contracts_are_active(self):
        payload = {"pod": [
            {"codice_pod": "IT001E0000000001", "forniture": [
                {"data_inizio_fornitura": "20200101", "data_fine_fornitura": ""}]},
            {"codice_pod": "IT001E0000000002", "forniture": [
                {"data_inizio_fornitura": "20200101", "data_fine_fornitura": "20991231"}]},
            {"codice_pod": "IT001E0000000003", "forniture": [
                {"data_inizio_fornitura": "20200101", "data_fine_fornitura": "20210101"}]},
        ]}
        codes = models.active_point_codes(payload, "pod", "codice_pod", date(2026, 11, 22))
        self.assertEqual(codes, ["IT001E0000000001", "IT001E0000000002"])

    def test_missing_list_means_no_supply(self):
        self.assertEqual(models.active_point_codes({}, "pdr", "codice_pdr", date.today()), [])

    def test_bad_shape_rejected(self):
        for payload in ([], "x", {"pdr": "x"}):
            with self.subTest(payload=payload), self.assertRaises(models.ResponseShapeError):
                models.active_point_codes(payload, "pdr", "codice_pdr", date.today())


class SeriesTests(unittest.TestCase):
    def test_merges_suppliers_and_prefers_latest_then_correction(self):
        payload = [
            {"misure_mensili": [
                electric_record("202501", 100, 50, data="20250205"),
                electric_record("202502", 80, data="20250305"),
            ]},
            {"contratto": {"misure_mensili": [
                electric_record("202501", 1, data="20250205", tipo="Rettifica"),
                electric_record("202502", 70, data="20250301"),
            ]}},
        ]
        series = models.build_series(models.ELECTRIC, "IT001E1", payload)
        self.assertEqual(series.months, {"202501": 1.0, "202502": 80.0})

    def test_monoraria_and_decimal_comma(self):
        payload = {"misure_mensili": [
            {"competenza_consumi": "202503", "delta_misure_monoraria": "12,5"}]}
        series = models.build_series(models.ELECTRIC, "X", payload)
        self.assertEqual(series.months, {"202503": 12.5})

    def test_gas_and_fallback_frequency(self):
        payload = {"misure_altre_frequenze": [
            {"competenza_consumi": "202412", "delta_misure": 30},
            {"competenza_consumi": "202413", "delta_misure": 99},
            {"competenza_consumi": "2024", "delta_misure": 99},
        ]}
        series = models.build_series(models.GAS, "123", payload)
        self.assertEqual(series.months, {"202412": 30.0})

    def test_years_and_latest(self):
        series = models.PointSeries("luce", "X", {"202511": 10.0, "202512": 5.0, "202601": 7.0})
        self.assertEqual(series.year_total(2025), 15.0)
        self.assertIsNone(series.year_total(2024))
        self.assertEqual(series.year_months(2026)["01"], 7.0)
        self.assertIsNone(series.year_months(2026)["02"])
        self.assertEqual(series.latest_month(), ("202601", 7.0))


class StatisticsTests(unittest.TestCase):
    def test_cumulative_fills_gaps_with_zero(self):
        series = models.PointSeries("gas", "1", {"202511": 10.0, "202602": 5.0})
        self.assertEqual(models.cumulative_months(series), [
            (2025, 11, 10.0, 10.0),
            (2025, 12, 0.0, 10.0),
            (2026, 1, 0.0, 10.0),
            (2026, 2, 5.0, 15.0),
        ])

    def test_statistic_id_is_safe(self):
        self.assertEqual(
            models.statistic_id("consumi_sii", "luce", "IT001E-123 4"),
            "consumi_sii:luce_it001e_123_4",
        )

    def test_mask_code(self):
        self.assertEqual(models.mask_code("IT001E12345678"), "…5678")


if __name__ == "__main__":
    unittest.main()
