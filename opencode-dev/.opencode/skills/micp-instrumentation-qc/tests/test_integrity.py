"""Unit tests for integrity module (raw hashing, audit-log hash chain, tamper detection)."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from integrity import sha256_of, sha256_file, verify_raw, append_log, verify_log


def test_sha256_of_deterministic():
    a = sha256_of({"b": 1, "a": [1, 2]})
    b = sha256_of({"a": [1, 2], "b": 1})
    assert a == b  # key order independent


def test_sha256_of_distinct():
    assert sha256_of({"a": 1}) != sha256_of({"a": 2})


def test_verify_raw_inline():
    res = verify_raw([{"sample": "x", "value": 1.0}])
    assert res["status"] == "ok"
    assert res["results"][0]["sha256"] == sha256_of({"sample": "x", "value": 1.0})


def test_verify_raw_file(tmp_path):
    p = tmp_path / "raw.csv"
    p.write_text("id,value\n1,7.0\n", encoding="utf-8")
    res = verify_raw([str(p)])
    assert res["results"][0]["kind"] == "file"
    assert res["results"][0]["sha256"] == sha256_file(str(p))


def test_append_log_chain(tmp_path):
    log = tmp_path / "audit.jsonl"
    e1 = {"kind": "qc", "task_id": "t1"}
    e2 = {"kind": "qc", "task_id": "t2"}
    r1 = append_log(e1, str(log))
    r2 = append_log(e2, str(log))
    assert r1["tail_hash"] != r2["tail_hash"]
    assert r2["appended"]["prev_hash"] == r1["tail_hash"]


def test_append_log_rejects_prev_hash_mismatch(tmp_path):
    log = tmp_path / "audit.jsonl"
    append_log({"kind": "qc", "task_id": "t1"}, str(log))
    with pytest.raises(ValueError):
        append_log({"kind": "qc", "task_id": "t2"}, str(log), prev_hash="deadbeef")


def test_verify_log_ok(tmp_path):
    log = tmp_path / "audit.jsonl"
    append_log({"kind": "qc", "task_id": "t1"}, str(log))
    append_log({"kind": "qc", "task_id": "t2"}, str(log))
    res = verify_log(str(log))
    assert res["chain_ok"] is True
    assert res["entries"] == 2


def test_verify_log_detects_tamper(tmp_path):
    log = tmp_path / "audit.jsonl"
    append_log({"kind": "qc", "task_id": "t1"}, str(log))
    append_log({"kind": "qc", "task_id": "t2"}, str(log))
    # Tamper: rewrite the first entry's content without updating its hash.
    lines = open(log, encoding="utf-8").read().splitlines()
    first = json.loads(lines[0])
    first["task_id"] = "t1-TAMPERED"
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps(first, sort_keys=True) + "\n")
        f.write(lines[1] + "\n")
    res = verify_log(str(log))
    assert res["chain_ok"] is False
    assert res["broken_at"] == 0


def test_verify_log_detects_broken_chain(tmp_path):
    log = tmp_path / "audit.jsonl"
    append_log({"kind": "qc", "task_id": "t1"}, str(log))
    append_log({"kind": "qc", "task_id": "t2"}, str(log))
    # Tamper: sever the link by rewriting entry 2's prev_hash.
    lines = open(log, encoding="utf-8").read().splitlines()
    second = json.loads(lines[1])
    second["prev_hash"] = "bad"
    with open(log, "w", encoding="utf-8") as f:
        f.write(lines[0] + "\n")
        f.write(json.dumps(second, sort_keys=True) + "\n")
    res = verify_log(str(log))
    assert res["chain_ok"] is False
