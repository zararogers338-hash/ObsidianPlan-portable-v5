"""Unit tests for sample_chain module."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from sample_chain import check_samples, generate_barcode, validate_barcode, barcode_checksum


def _s(sid, barcode=None, coll="2026-08-01T09:00:00"):
    s = {"sample_id": sid, "collection_time": coll}
    if barcode:
        s["barcode"] = barcode
    return s


def test_generate_and_validate_barcode():
    bc = generate_barcode("S-001")
    assert validate_barcode(bc) is True
    # tampered barcode fails
    assert validate_barcode(bc[:-1] + ("X" if bc[-1] != "X" else "Y")) is False


def test_barcode_checksum_known():
    # body "ABC" -> indices 10+11+12=33 -> 33 % 43 = 33 -> char 'X'
    assert barcode_checksum("ABC") == "X"


def test_no_duplicates():
    res = check_samples({"samples": [_s("S-001"), _s("S-002")]})
    assert res["duplicate_ids"] == []


def test_duplicate_detected():
    res = check_samples({"samples": [_s("S-001"), _s("S-001")]})
    assert res["duplicate_ids"] == ["S-001"]
    flags = [f["flag"] for f in res["flags"]]
    assert "DUPLICATE_ID" in flags


def test_invalid_barcode_flagged():
    res = check_samples({"samples": [_s("S-001", barcode="S-001XX")]})
    flags = [f["flag"] for f in res["flags"]]
    assert "BARCODE_INVALID" in flags


def test_rejects_no_samples():
    with pytest.raises(ValueError):
        check_samples({"samples": []})
