"""Unit tests for _common: error codes, numeric validation, unit conversion, semver."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
import _common


def test_error_codes_table():
    assert len(_common.ERROR_CODES) == 11
    for code in _common.ERROR_CODE_IDS:
        assert code.startswith("MICQ-E")
        assert "message" in _common.ERROR_CODES[code]
        assert isinstance(_common.ERROR_CODES[code]["retryable"], bool)


def test_error_object():
    e = _common.error("MICQ-E1003", {"detail": "x"})
    assert e["code"] == "MICQ-E1003"
    assert e["retryable"] is False
    assert e["details"] == {"detail": "x"}
    # unknown code falls back to MICQ-E1011
    e2 = _common.error("MICQ-E9999")
    assert e2["code"] == "MICQ-E1011"


def test_check_numeric():
    assert _common.check_numeric(1.0, "x") == []
    assert _common.check_numeric(None, "x") != []
    assert _common.check_numeric(float("nan"), "x") != []
    assert _common.check_numeric(-1, "x", nonnegative=True) != []
    assert _common.check_numeric(5, "x", lower=10) != []
    assert _common.check_numeric(15, "x", upper=10) != []
    assert _common.check_numeric("abc", "x") != []


def test_unit_conversions():
    assert abs(_common.to_si(1.0, "MPa", "pressure") - 1e6) < 1e-6
    assert abs(_common.to_si(1.0, "mM", "concentration") - 1e-3) < 1e-12
    assert abs(_common.to_si(1.0, "uL/min", "flow") - 1e-9 / 60) < 1e-18
    assert abs(_common.to_si(1.0, "mS/cm", "ec") - 1000.0) < 1e-6
    assert abs(_common.to_si(1.0, "bar", "pressure") - 1e5) < 1e-6


def test_unit_normalize_case_insensitive():
    assert _common.normalize_unit("MM", "concentration") == "mM"
    assert _common.normalize_unit("Mpa", "pressure") == "MPa"


def test_unit_invariant():
    assert _common.unit_invariant(1.0, "kPa", 1000.0, "Pa", "pressure") is True
    assert _common.unit_invariant(1.0, "kPa", 1.0, "MPa", "pressure") is False


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        _common.normalize_unit("furlongs", "pressure")


def test_semver():
    assert _common.is_semver("1.2.3")
    assert not _common.is_semver("1.2")
    assert not _common.is_semver("v1.2.3")
    assert _common.parse_semver("1.2.3") == (1, 2, 3)
