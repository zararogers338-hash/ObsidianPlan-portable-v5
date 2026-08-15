"""micp-instrumentation-qc: instrument export format standardization + unit normalization.

Pure Python standard library. Deterministic. Parses common instrument export
rows (CSV-like header maps) into a normalized measurement record, and normalizes
unit strings into canonical units (see _common.UNITS).

The parser is deliberately conservative: it detects separators, strips units from
column headers, and coerces numeric cells. It never guesses values.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from _common import normalize_unit, to_si

# Header aliases -> normalized measurement field.
_FIELD_ALIASES: dict[str, str] = {
    "sample": "sample_id",
    "sample_id": "sample_id",
    "id": "sample_id",
    "barcode": "barcode",
    "time": "timestamp",
    "timestamp": "timestamp",
    "datetime": "timestamp",
    "measured_at": "timestamp",
    "value": "value",
    "reading": "value",
    "measurement": "value",
    "signal": "value",
    "conc": "value",
    "concentration": "value",
    "unit": "unit",
    "instrument": "instrument_id",
    "instrument_id": "instrument_id",
    "sensor": "instrument_id",
    "method": "method",
}


def parse_instrument_csv(text: str, delimiter: str | None = None) -> list[dict[str, Any]]:
    """Parse an instrument CSV/TSV export into normalized measurement records.

    Unit suffixes in headers like 'value (mg/L)' or 'signal [uS/cm]' are stripped
    into a per-row 'unit' field when present.
    """
    sniffer = csv.Sniffer()
    try:
        if delimiter is None:
            delimiter = sniffer.sniff(text[:4096], delimiters=",;\t").delimiter
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except Exception:
        rows = list(csv.reader(io.StringIO(text), delimiter=","))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    unit_hint: str | None = None
    mapped = []
    for h in header:
        m = re.match(r"^(value|reading|signal|conc|concentration|measurement)\s*[\(\[]\s*(.+?)\s*[\)\]]$", h)
        if m:
            unit_hint = m.group(2).strip()

    # Best-effort case preservation: re-match the raw (un-lowercased) header to
    # recover the exact unit string the instrument used.
    if unit_hint and rows:
        for h in rows[0]:
            m = re.match(r"^(value|reading|signal|conc|concentration|measurement)\s*[\(\[]\s*(.+?)\s*[\)\]]$", h.strip())
            if m and m.group(1).lower() in ("value", "reading", "signal", "conc", "concentration", "measurement"):
                unit_hint = m.group(2).strip()
                break

    for raw in rows[1:]:
        rec: dict[str, Any] = {}
        for i, h in enumerate(header):
            if i >= len(raw):
                continue
            cell = raw[i].strip()
            if not cell:
                continue
            # Headers like 'value (mg/L)' / 'signal [uS/cm]' are value columns.
            unit_match = re.match(r"^(value|reading|signal|conc|concentration|measurement)\s*[\(\[]\s*.+?\s*[\)\]]$", h)
            field = "value" if unit_match else _FIELD_ALIASES.get(h)
            if field == "value":
                try:
                    rec["value"] = float(cell)
                except ValueError:
                    continue
            elif field == "unit":
                rec["unit"] = cell
            elif field == "timestamp":
                rec["timestamp"] = cell
            else:
                rec.setdefault(field, cell)
        if unit_hint and "unit" not in rec:
            rec["unit"] = unit_hint
        if "value" in rec and "unit" not in rec:
            rec["unit"] = "1"
        if rec:
            mapped.append(rec)
    return mapped


def normalize_units(records: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    """Normalize the 'unit' field of each record to a canonical unit for `dimension`.

    Raises MICQ-E1003 for an unrecognized unit. Non-destructive: returns new records.
    """
    out = []
    for r in records:
        r = dict(r)
        u = r.get("unit")
        if u and not _is_dimensionless(u):
            r["unit"] = normalize_unit(u, dimension)
            if "value" in r:
                r["value_si"] = to_si(float(r["value"]), u, dimension)
        out.append(r)
    return out


def _is_dimensionless(u: str) -> bool:
    return u.strip().lower() in {"%", "ratio", "n/a", "none", "dimensionless", "ppm", "ppb", "unitless", ""}


def run(data: dict[str, Any]) -> dict[str, Any]:
    action = data.get("action", "parse")
    if action == "parse":
        text = data.get("csv")
        if not isinstance(text, str):
            raise ValueError("MICQ-E1001: 'csv' field required for adapters parse")
        return {"records": parse_instrument_csv(text)}
    if action == "normalize":
        records = data.get("records") or []
        dimension = data.get("dimension")
        if not dimension:
            raise ValueError("MICQ-E1001: 'dimension' required for adapters normalize")
        return {"records": normalize_units(records, dimension)}
    raise ValueError(f"MICQ-E1003: unknown adapters action '{action}'")
