"""Unit tests for adapters module (instrument export parsing + unit normalization)."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from adapters import parse_instrument_csv, normalize_units
from _common import to_si


def test_parse_comma_csv():
    text = "sample_id,value,unit,timestamp\nS-1,7.02,pH,2026-08-01T10:00:00\n"
    recs = parse_instrument_csv(text)
    assert len(recs) == 1
    assert recs[0]["sample_id"] == "S-1"
    assert recs[0]["value"] == 7.02


def test_parse_tab_csv():
    text = "sample\tvalue\tunit\nS-1\t7.02\tpH\n"
    recs = parse_instrument_csv(text)
    assert recs[0]["value"] == 7.02


def test_parse_unit_suffix_in_header():
    text = "sample_id,value (mg/L),timestamp\nS-1,12.5,2026-08-01T10:00:00\n"
    recs = parse_instrument_csv(text)
    assert recs[0]["unit"] == "mg/L"
    assert recs[0]["value"] == 12.5


def test_normalize_units_concentration_mass():
    recs = [{"value": 12.5, "unit": "mg/L"}]
    out = normalize_units(recs, "concentration_mass")
    assert out[0]["unit"] == "mg/L"
    assert out[0]["value_si"] == pytest.approx(12.5e-3)


def test_normalize_units_rejects_cross_dimension():
    # mg/L is a mass-per-volume concentration; the molar dimension must reject it.
    with pytest.raises(ValueError):
        normalize_units([{"value": 12.5, "unit": "mg/L"}], "concentration")


def test_normalize_units_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_units([{"value": 1, "unit": "furlongs/fortnight"}], "flow")


def test_to_si_pressure():
    assert abs(to_si(1.0, "MPa", "pressure") - 1e6) < 1e-6
    assert abs(to_si(1.0, "bar", "pressure") - 1e5) < 1e-6


def test_to_si_ec():
    assert abs(to_si(1.0, "mS/cm", "ec") - 1000.0) < 1e-6
