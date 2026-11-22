"""Logica pura sulle risposte del Portale Consumi.

Non importa Home Assistant: è coperta dai test in ``tests/`` senza installazioni.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterator

ELECTRIC = "luce"
GAS = "gas"

_ELECTRIC_DELTA_KEYS = tuple(f"delta_misure_f{i}" for i in range(1, 7))
_STAT_ID_UNSAFE = re.compile(r"[^a-z0-9_]")


class ResponseShapeError(ValueError):
    """La risposta del portale non ha la forma attesa."""


@dataclass
class PointSeries:
    """Misure mensili di un POD o PDR, chiave ``YYYYMM``."""

    commodity: str
    code: str
    months: dict[str, float] = field(default_factory=dict)

    def year_months(self, year: int) -> dict[str, float | None]:
        """Gennaio-dicembre di un anno, ``None`` dove manca la misura."""
        return {
            f"{month:02d}": self.months.get(f"{year}{month:02d}")
            for month in range(1, 13)
        }

    def year_total(self, year: int) -> float | None:
        values = [v for v in self.year_months(year).values() if v is not None]
        return round(sum(values), 3) if values else None

    def latest_month(self) -> tuple[str, float] | None:
        """Ultima competenza disponibile (``YYYYMM``, valore)."""
        if not self.months:
            return None
        key = max(self.months)
        return key, self.months[key]


def parse_date(value: Any) -> date | None:
    """Converte una data ``YYYYMMDD`` del portale."""
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def active_point_codes(
    payload: Any,
    point_key: str,
    code_key: str,
    today: date,
) -> list[str]:
    """POD/PDR con almeno un contratto attivo oggi."""
    if not isinstance(payload, dict):
        raise ResponseShapeError("La risposta forniture non è un oggetto JSON.")
    points = payload.get(point_key)
    if points is None:
        # Nessuna fornitura di questo tipo (es. casa senza gas).
        return []
    if not isinstance(points, list):
        raise ResponseShapeError(
            f"La risposta forniture contiene {point_key} in forma inattesa."
        )

    codes: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        code = point.get(code_key)
        supplies = point.get("forniture")
        if not isinstance(code, str) or not code.strip() or not isinstance(supplies, list):
            continue

        for supply in supplies:
            if not isinstance(supply, dict):
                continue
            start = parse_date(supply.get("data_inizio_fornitura"))
            end_value = supply.get("data_fine_fornitura")
            end = parse_date(end_value)
            # Fine vuota = contratto corrente; fine futura = ancora attivo.
            end_is_open = end_value in (None, "")
            starts_by_today = start is None or start <= today
            ends_after_today = end_is_open or (end is not None and end >= today)
            if starts_by_today and ends_after_today:
                codes.add(code.strip())
                break

    return sorted(codes)


def iter_monthly_records(payload: Any) -> Iterator[dict]:
    """Legge ``misure_mensili``; ``misure_altre_frequenze`` solo come ripiego."""
    if isinstance(payload, list):
        for item in payload:
            yield from iter_monthly_records(item)
        return
    if not isinstance(payload, dict):
        return

    monthly = payload.get("misure_mensili")
    other_frequency = payload.get("misure_altre_frequenze")
    if isinstance(monthly, list):
        yield from (r for r in monthly if isinstance(r, dict))
    elif isinstance(other_frequency, list):
        yield from (r for r in other_frequency if isinstance(r, dict))

    for key, value in payload.items():
        if key not in ("misure_mensili", "misure_altre_frequenze"):
            yield from iter_monthly_records(value)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_consumption(record: dict, commodity: str) -> float | None:
    """Delta di consumo di una misura (somma delle fasce per la luce)."""
    if commodity == GAS:
        return _number(record.get("delta_misure"))

    fasce = [_number(record.get(key)) for key in _ELECTRIC_DELTA_KEYS]
    if any(value is not None for value in fasce):
        return sum(value for value in fasce if value is not None)
    return _number(record.get("delta_misure_monoraria"))


def build_series(commodity: str, code: str, payload: Any) -> PointSeries:
    """Unisce contratti e gestori dello stesso punto in una serie mensile.

    Per ogni competenza tiene la lettura più recente; a parità di data
    preferisce una rettifica a una lettura periodica.
    """
    selected: dict[str, tuple[tuple[str, int], float]] = {}
    for record in iter_monthly_records(payload):
        competence = str(record.get("competenza_consumi", ""))
        if len(competence) != 6 or not competence.isdigit():
            continue
        if not 1 <= int(competence[4:]) <= 12:
            continue
        value = record_consumption(record, commodity)
        if value is None:
            continue
        reading_date = str(record.get("data_lettura") or "")
        is_correction = int("rettifica" in str(record.get("tipo_misura", "")).lower())
        rank = (reading_date, is_correction)
        previous = selected.get(competence)
        if previous is None or rank > previous[0]:
            selected[competence] = (rank, value)

    return PointSeries(
        commodity=commodity,
        code=code,
        months={k: round(v, 3) for k, (_, v) in sorted(selected.items())},
    )


def statistic_id(domain: str, commodity: str, code: str) -> str:
    """ID di statistica esterna valido per il recorder (``dominio:oggetto``)."""
    return f"{domain}:{commodity}_{_STAT_ID_UNSAFE.sub('_', code.lower())}"


def cumulative_months(series: PointSeries) -> list[tuple[int, int, float, float]]:
    """(anno, mese, consumo, somma progressiva) dalla prima competenza.

    I mesi mancanti tra due misure valgono 0, così la somma resta monotona.
    """
    if not series.months:
        return []
    keys = sorted(series.months)
    year, month = int(keys[0][:4]), int(keys[0][4:])
    last_year, last_month = int(keys[-1][:4]), int(keys[-1][4:])
    rows: list[tuple[int, int, float, float]] = []
    total = 0.0
    while (year, month) <= (last_year, last_month):
        value = series.months.get(f"{year}{month:02d}", 0.0)
        total = round(total + value, 3)
        rows.append((year, month, value, total))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return rows


def mask_code(code: str) -> str:
    """Codice abbreviato per i nomi visibili (ultime 4 cifre)."""
    code = code.strip()
    return f"…{code[-4:]}" if len(code) > 4 else code
