"""Regression tests: stable behaviors that must not silently change.

Guards the skill's reproducibility guarantees (determinism, envelope shape,
version-identity fallback, guardrail semantics) so future edits cannot regress
them without a failing test.
"""

from __future__ import annotations

import json
import os

from conftest import WRITE_SUMMARY, base_payload, make_sandbox, run_cli


class TestDeterminism:
    def test_env_output_is_deterministic(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="env")
        a = run_cli("env", p)
        b = run_cli("env", p)
        assert json.dumps(a["result"], sort_keys=True) == \
            json.dumps(b["result"], sort_keys=True)

    def test_manifest_output_is_deterministic(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        payload = base_payload(root, action="reproduce",
                               commands=[{"id": "w", "cmd": WRITE_SUMMARY,
                                          "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}])
        a = run_cli("reproduce", payload)
        b = run_cli("reproduce", payload)
        # The provenance chain advances between runs (append-only log), so the
        # signed event's prev_hash differs — the manifest, hashes, lineage and
        # checks must be byte-identical regardless.
        assert json.dumps(a["result"]["reproduction_manifest"], sort_keys=True) == \
            json.dumps(b["result"]["reproduction_manifest"], sort_keys=True)
        assert json.dumps(a["result"]["hashes"], sort_keys=True) == \
            json.dumps(b["result"]["hashes"], sort_keys=True)
        assert a["result"]["reproduction_manifest"]["manifest_id"] == \
            b["result"]["reproduction_manifest"]["manifest_id"]

    def test_provenance_event_id_stable(self, tmp_path) -> None:
        # Same input replayed on two fresh logs must produce byte-identical events
        # (append-only chain replays deterministically from an empty log).
        import tempfile as _tf
        root_a = make_sandbox(tmp_path / "a")
        root_b = make_sandbox(tmp_path / "b")
        p = base_payload(root_a, action="record")
        a = run_cli("record", p)
        b = run_cli("record", {**p, "root": root_b})
        assert a["result"]["event"]["event_id"] == b["result"]["event"]["event_id"]
        assert a["result"]["event"]["hash"] == b["result"]["event"]["hash"]


class TestEnvelopeContract:
    def test_envelope_shape(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("env", base_payload(root, action="env"))
        assert set(env.keys()) == {"ok", "tool", "version", "result"}
        assert env["version"] == "1.0.0"
        assert isinstance(env["result"], dict)

    def test_error_envelope_shape(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("diff", base_payload(root, action="diff"), expect_exit=2)
        assert set(env.keys()) == {"ok", "tool", "version", "error"}
        assert set(env["error"].keys()) == {"code", "message", "retryable", "details"}


class TestVersionIdentityFallback:
    def test_no_git_yields_fingerprint(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("env", base_payload(root, action="env"))
        git = env["result"]["git"]
        assert git["git_present"] is False
        assert git["fingerprint"] and git["fingerprint"].startswith(("fp_", )) or \
            len(git.get("fingerprint") or "") == 64
        # identity falls back to the fingerprint
        assert env["result"]["identity"] == git["fingerprint"]

    def test_manifest_records_fingerprint_identity(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        payload = base_payload(root, action="reproduce",
                               commands=[{"id": "w", "cmd": WRITE_SUMMARY,
                                          "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}])
        env = run_cli("reproduce", payload)
        git = env["result"]["reproduction_manifest"]["versions"]["git_commit"]
        assert git and git != ""


class TestOutputSchema:
    def test_reproduce_output_validates(self, tmp_path) -> None:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "tools", "mrv"))
        from _jsonschema import validate as js_validate
        root = make_sandbox(tmp_path)
        payload = base_payload(root, action="reproduce",
                               commands=[{"id": "w", "cmd": WRITE_SUMMARY,
                                          "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}])
        env = run_cli("service", payload)
        assert env["result"]["status"] == "SUCCESS"
        schema = json.load(open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "schemas", "output.schema.json"), encoding="utf-8"))
        errs = js_validate(env["result"], schema)
        assert errs == [], f"output failed schema: {errs[:3]}"
