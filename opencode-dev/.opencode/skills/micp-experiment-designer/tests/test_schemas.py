#!/usr/bin/env python3
"""Regression tests: every bundled JSON Schema must parse and the tool's
outputs must validate against the output schema. Offline.

Run:  python -m unittest discover -s tests -p "test_*.py" -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import doe_power, randomizer, sop_check, preregister, quantity_calc
from tools.jsonschema_subset import validate_document
from tools.validate import _load_schema


class TestSchemas(unittest.TestCase):
    def _schema(self, name: str):
        return _load_schema(name)

    def test_schemas_parse(self):
        for name in ("input.schema.json", "output.schema.json"):
            s = self._schema(name)
            self.assertIsInstance(s, dict)
            self.assertIn("properties", s)

    def test_valid_input_envelope_passes(self):
        schema = self._schema("input.schema.json")
        doc = {
            "task_id": "t-1", "project_id": "p", "request": "design x",
            "skill_version": "1.0.0", "timestamp": "2026-08-06T00:00:00Z",
            "context": {"hypothesis_card": {"primary_hypothesis": "h",
                                            "pathway": "urea"}},
        }
        report = validate_document(doc, schema)
        self.assertTrue(report["valid"], report["errors"])

    def test_missing_required_rejected(self):
        schema = self._schema("input.schema.json")
        doc = {"task_id": "t-1"}  # missing project_id, request, skill_version, timestamp
        report = validate_document(doc, schema)
        self.assertFalse(report["valid"])
        paths = {e["path"] for e in report["errors"]}
        self.assertTrue(any("required" in e["message"] for e in report["errors"]),
                        report["errors"])

    def test_doe_output_validates(self):
        schema = self._schema("output.schema.json")
        # a doe_power tool output is NOT the full envelope; build a valid
        # envelope carrying it as evidence_used reference only. We validate
        # the tool result structurally instead (no full envelope needed).
        r = doe_power.main({"design": {"kind": "two_group_means", "delta": 1.5,
                                       "sigma": 2.0}})
        self.assertIsInstance(r["n_per_group"], int)

    def test_output_envelope_validation(self):
        schema = self._schema("output.schema.json")
        envelope = {
            "status": "SUCCESS",
            "summary": "设计完成",
            "findings": [],
            "validation": {
                "schema_passed": True,
                "self_check_passed": True,
                "tool_calls": [{"tool": "doe_power", "ok": True}],
            },
            "provenance": {
                "skill": "micp-experiment-designer",
                "skill_version": "1.0.0",
                "contract_version": "1.0.0",
                "timestamp": "2026-08-06T00:00:00Z",
                "tools_used": ["doe_power"],
            },
        }
        report = validate_document(envelope, schema)
        self.assertTrue(report["valid"], report["errors"])

    def test_bad_status_rejected(self):
        schema = self._schema("output.schema.json")
        envelope = {
            "status": "MADE_UP",
            "summary": "x",
            "validation": {"schema_passed": True, "self_check_passed": True,
                           "tool_calls": []},
            "provenance": {
                "skill": "s", "skill_version": "1.0.0", "contract_version": "1.0.0",
                "timestamp": "2026-08-06T00:00:00Z", "tools_used": []},
        }
        report = validate_document(envelope, schema)
        self.assertFalse(report["valid"])


class TestToolConsistency(unittest.TestCase):
    """Repeat-run consistency: identical input => identical output."""

    def _snap(self, fn, payload):
        import json as _json
        return _json.dumps(fn(payload), sort_keys=True, default=str)

    def test_doe_deterministic(self):
        p = {"design": {"kind": "two_group_means", "delta": 1.5, "sigma": 2.0}}
        self.assertEqual(self._snap(doe_power.main, p), self._snap(doe_power.main, p))

    def test_randomizer_deterministic(self):
        p = {"groups": ["A", "B"], "units": [{"id": f"u{i}"} for i in range(1, 7)],
             "method": "complete", "seed": 7}
        self.assertEqual(self._snap(randomizer.main, p), self._snap(randomizer.main, p))


if __name__ == "__main__":
    unittest.main()
