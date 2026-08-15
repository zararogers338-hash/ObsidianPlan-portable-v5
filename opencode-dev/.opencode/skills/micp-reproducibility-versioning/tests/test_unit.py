"""Unit tests for micp-reproducibility-versioning primitives.

Covers the pure machinery (canonical JSON, hashing, fingerprints, seed RNG,
semver parsing, schema validation, diff, provenance chain) without filesystem
state beyond tmp dirs.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "mrv"))

from _common import (ToolError, canonical_json, dir_fingerprint, sha256_file,
                     sha256_hex, stable_hash, walk_files)  # noqa: E402
from _jsonschema import SchemaError, validate  # noqa: E402
from diff import deep_diff, diff_hashes  # noqa: E402
from envinfo import parse_semver, version_gate  # noqa: E402
from provenance import (ZERO_HASH, _event_body, _write_event, load_log,
                        verify_chain)  # noqa: E402
from seed import Pcg32, derive_seed, resolve_seed, splitmix64  # noqa: E402


class TestHashing:
    def test_sha256_known_vector(self) -> None:
        assert sha256_hex("abc") == \
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    def test_canonical_json_deterministic(self) -> None:
        a = {"b": 1, "a": [2, 1]}
        b = {"a": [2, 1], "b": 1}
        assert canonical_json(a) == canonical_json(b)
        assert stable_hash(a) == stable_hash(b)

    def test_dir_fingerprint_changes_with_content(self, tmp_path) -> None:
        (tmp_path / "f.txt").write_text("one")
        fp1 = dir_fingerprint(str(tmp_path))
        (tmp_path / "f.txt").write_text("two")
        fp2 = dir_fingerprint(str(tmp_path))
        assert fp1 != fp2

    def test_walk_files_hides_hidden(self, tmp_path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / ".secret").write_text("s")
        assert walk_files(str(tmp_path)) == ["a.txt"]


class TestSeed:
    def test_splitmix64_reference(self) -> None:
        # Reference values for splitmix64 stream starting from state 0.
        outs = []
        s = 0
        for _ in range(3):
            s, o = splitmix64(s)
            outs.append(o)
        assert outs == [
            0xE220A8397B1DCDAF,
            0x6E789E6AA1B965F4,
            0x6C45D188009454F,
        ]

    def test_pcg32_repeatable(self) -> None:
        r1 = Pcg32(42)
        r2 = Pcg32(42)
        assert [r1.next_float() for _ in range(5)] == [r2.next_float() for _ in range(5)]
        r3 = Pcg32(43)
        assert r1.next_float() != r3.next_float()

    def test_pcg32_range(self) -> None:
        r = Pcg32(7)
        for _ in range(100):
            v = r.next_float()
            assert 0.0 <= v < 1.0

    def test_derive_seed_stable(self) -> None:
        assert derive_seed("2026-08-07T00:00:00Z") == derive_seed("2026-08-07T00:00:00Z")
        assert derive_seed("2026-08-07T00:00:00Z") != derive_seed("2026-08-08T00:00:00Z")

    def test_resolve_seed_policies(self) -> None:
        p = {"seed_policy": "generate", "timestamp": "2026-08-07T00:00:00Z"}
        gen = resolve_seed(p)
        assert gen["policy"] == "generate"
        reuse = resolve_seed({"seed_policy": "reuse", "random_seed": 5})
        assert reuse["value"] == 5
        default = resolve_seed({"seed_policy": "reuse"})
        assert default["value"] == 0
        with pytest.raises(ToolError):
            resolve_seed({"seed_policy": "require"})
        with pytest.raises(ToolError):
            resolve_seed({"seed_policy": "bogus"})


class TestSemver:
    def test_parse(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)
        assert parse_semver("1.2.3-alpha") == (1, 2, 3)
        assert parse_semver("not-a-version") is None

    def test_version_gate(self) -> None:
        ok = {"skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0"}
        assert version_gate(ok) == []
        assert "MRV-E801" in version_gate({"skill_version": "2.0.0",
                                           "controller_version": "x"})[0]
        assert any("skill_version missing" in p for p in version_gate({}))
        assert any("controller_version missing" in p for p in version_gate({"skill_version": "1.0.0"}))


class TestJsonschema:
    def test_rejects_unsupported_keywords(self) -> None:
        with pytest.raises(SchemaError):
            validate({}, {"type": "object", "unevaluatedProperties": False})

    def test_basic_object(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["a"],
            "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        }
        assert validate({"a": 1}, schema) == []
        assert validate({"a": 1, "c": 2}, schema) != []
        assert validate({"b": "x"}, schema) != []  # missing required a

    def test_ref(self) -> None:
        schema = {
            "type": "object",
            "properties": {"x": {"$ref": "#/$defs/n"}},
            "$defs": {"n": {"type": "number", "minimum": 0}},
        }
        assert validate({"x": 3}, schema) == []
        assert validate({"x": -1}, schema) != []

    def test_const_enum_combinations(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "status": {"enum": ["SUCCESS", "BLOCKED"]},
                "kind": {"const": "reproduce"},
            },
        }
        assert validate({"status": "SUCCESS", "kind": "reproduce"}, schema) == []
        assert validate({"status": "FAILED", "kind": "reproduce"}, schema) != []


class TestDiff:
    def test_deep_diff_identical(self) -> None:
        a = {"x": [1, 2], "y": "z"}
        assert deep_diff(a, dict(a)) == []

    def test_deep_diff_modified(self) -> None:
        diffs = deep_diff({"x": 1, "y": {"a": 1}}, {"x": 2, "y": {"a": 1}})
        assert any(d["kind"] == "modified" and d["path"] == ".x" for d in diffs)

    def test_hash_diff(self) -> None:
        diffs = diff_hashes({"a": "1" * 64}, {"a": "2" * 64, "b": "3" * 64})
        kinds = {d["kind"] for d in diffs}
        assert kinds == {"hash_mismatch", "added"}


class TestProvenanceChain:
    def test_chain_intact_then_tampered(self, tmp_path) -> None:
        ev1 = _write_event(str(tmp_path), "log.jsonl",
                           {"schema_version": "1.0.0", "prev_hash": ZERO_HASH, "n": 1})
        ev2 = _write_event(str(tmp_path), "log.jsonl",
                           {"schema_version": "1.0.0", "prev_hash": ev1["hash"], "n": 2})
        events = load_log(str(tmp_path), "log.jsonl")
        assert verify_chain(events) == []
        # tamper with event 2's content
        events[1]["n"] = 99
        assert len(verify_chain(events)) >= 1

    def test_prev_hash_links(self, tmp_path) -> None:
        ev1 = _write_event(str(tmp_path), "log.jsonl",
                           {"schema_version": "1.0.0", "prev_hash": ZERO_HASH, "n": 1})
        ev2 = _write_event(str(tmp_path), "log.jsonl",
                           {"schema_version": "1.0.0", "prev_hash": ev1["hash"], "n": 2})
        events = load_log(str(tmp_path), "log.jsonl")
        assert events[1]["prev_hash"] == events[0]["hash"]
        assert ev2["hash"] != events[0]["hash"]
        assert ev2["hash"] != ev1["hash"]
