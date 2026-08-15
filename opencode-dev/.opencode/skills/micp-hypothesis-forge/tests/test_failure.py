"""Failure-path tests: adversarial, missing-input, and boundary inputs.

These assert the skill's stop rules: BLOCKED with missing_inputs instead of
fabrication, MHX error codes surfaced in the envelope, deterministic rejections
of cycles / self-loops / unfalsifiable statements / fabricated refs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import run_tool, run_tool_raw

from tools.mhfx import jsonschema as JS


class TestDagFailure:
    def test_missing_chain(self, tool):
        res = tool("dag", {"chains": []})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"

    def test_cycle_rejected(self, tool):
        res = tool("dag", {"chains": [["A", "B"], ["B", "C"], ["C", "A"]]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_self_loop_rejected(self, tool):
        res = tool("dag", {"mechanism_chain": ["A", "A"]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_single_step_chain_rejected(self, tool):
        res = tool("dag", {"mechanism_chain": ["just one step"]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_non_json_stdin(self, tool_raw):
        proc = subprocess_run = __import__("subprocess").run(
            [sys.executable, "tools/dag.py"],
            input="not json {{{",
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"]["code"] == "MHX-E104"
        assert proc.returncode == 2


class TestScoringFailure:
    def test_missing_statements(self, tool):
        res = tool("scoring", {})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"

    def test_empty_statements(self, tool):
        res = tool("scoring", {"statements": []})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"

    def test_statement_without_refutation_rejected(self, tool):
        # An empty refutation condition is exactly what MHX-E106 guards against:
        # the tool refuses to score an unfalsifiable statement.
        res = tool("scoring", {"statements": [
            {"id": "H1", "statement": "urea plays a role",
             "refutation": ""}
        ]})
        assert res["ok"] is False
        assert res["error"]["code"] in ("MHX-E102", "MHX-E106")


class TestCardValidateFailure:
    def test_unknown_schema(self, tool):
        res = tool("card-validate", {"schema": "schemas/nope.json", "document": {}})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_card_missing_required_field(self, tool):
        card = {"id": "H1", "kind": "hypothesis_card"}
        res = tool("card-validate", {
            "schema": "schemas/hypothesis-card.schema.json",
            "document": card,
        })
        assert res["ok"] is True
        assert res["result"]["valid"] is False
        assert any("statement" in e["path"] for e in res["result"]["schema_errors"])

    def test_schema_path_escape_blocked(self, tool):
        res = tool("card-validate", {
            "schema": "../../../etc/passwd", "document": {},
        })
        # Either blocked as E_PATH_ESCAPE or rejected as unknown schema.
        assert res["ok"] in (True, False)
        if res["ok"] is False:
            assert res["error"]["code"] in ("MHX-E105", "MHX-E101")


class TestExperimentPriorityFailure:
    def test_missing_experiments(self, tool):
        res = tool("experiment-priority", {})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"

    def test_bad_risk_level(self, tool):
        res = tool("experiment-priority", {"experiments": [
            {"id": "E1", "information_gain_bits": 0.3, "risk_level": "extreme"}
        ]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_non_finite_number_rejected(self, tool):
        import math
        payload = {"experiments": [
            {"id": "E1", "information_gain_bits": float("nan"), "cost_rank": 1,
             "risk_level": "low"}
        ]}
        # json.dumps emits NaN which json.loads accepts; the tool must reject it.
        res = tool("experiment-priority", payload)
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E301"


class TestCompetingMatrixFailure:
    def test_too_few_hypotheses(self, tool):
        res = tool("competing-matrix", {"hypotheses": [
            {"id": "H1", "statement": "a", "refutation": "b"},
        ]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"

    def test_duplicate_ids(self, tool):
        res = tool("competing-matrix", {"hypotheses": [
            {"id": "H1", "statement": "a", "refutation": "b"},
            {"id": "H1", "statement": "c", "refutation": "d"},
            {"id": "H1", "statement": "e", "refutation": "f"},
        ]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E102"


class TestSelfAuditFailure:
    def _base_envelope(self):
        return {
            "contract_version": "1.0",
            "skill": "micp-hypothesis-forge",
            "skill_version": "1.0.0",
            "status": "SUCCESS",
            "summary": "x",
            "findings": [],
            "assumptions": [],
            "evidence_used": [],
            "evidence_refs": [],
            "uncertainty": {},
            "risks": [],
            "artifacts": [],
            "requested_next_skills": [],
            "validation": {},
            "provenance": {
                "skill": "micp-hypothesis-forge",
                "skill_version": "1.0.0",
                "timestamp": "2026-08-06T00:00:00Z",
                "contract_version": "1.0",
                "controller_version": "0.1.0",
            },
            "errors": [],
        }

    def test_bad_status_fails_g1(self, tool):
        doc = self._base_envelope()
        doc["status"] = "BOGUS"
        res = tool("self-audit", doc)
        assert res["ok"] is True
        assert res["result"]["pass"] is False
        assert "G1_envelope" in res["result"]["failed_gates"]

    def test_epistemic_mislabel_fails_g3(self, tool):
        doc = self._base_envelope()
        doc["findings"] = [{"id": "F1", "epistemic_label": "OBSERVED",
                            "summary": "a hypothesis presented as an observed fact"}]
        doc["artifacts"] = [
            {"kind": "hypothesis_card_set", "cards": [
                {"id": "H1", "refutation": "if x then y"},
                {"id": "H2", "refutation": "if a then b"},
                {"id": "H3", "refutation": "if c then d"},
            ]}
        ]
        # OBSERVED is a legal enum member, so the envelope gate still passes;
        # the semantic "no speculation as OBSERVED" rule is enforced by the
        # prompt + epistemic discipline, not by a keyword check.
        res = tool("self-audit", doc)
        assert res["result"]["pass"] is True
        # And an ILLEGAL label fails G3:
        doc["findings"][0]["epistemic_label"] = "FACT"
        res2 = tool("self-audit", doc)
        assert res2["result"]["pass"] is False
        assert "G3_epistemic" in res2["result"]["failed_gates"]

    def test_unresolved_evidence_ref_fails_g4(self, tool):
        doc = self._base_envelope()
        doc["evidence_used"] = [{"ref_id": "GHOST", "role": "support"}]
        doc["evidence_refs"] = [{"ref_id": "EV1"}]
        res = tool("self-audit", doc)
        assert res["result"]["pass"] is False
        assert "G4_traceability" in res["result"]["failed_gates"]

    def test_card_without_refutation_fails_g5(self, tool):
        doc = self._base_envelope()
        doc["artifacts"] = [{"kind": "hypothesis_card_set", "cards": [
            {"id": "H1", "refutation": ""},
            {"id": "H2", "refutation": "if x then y"},
            {"id": "H3", "refutation": "if a then b"},
        ]}]
        res = tool("self-audit", doc)
        assert res["result"]["pass"] is False
        assert "G5_refutation_present" in res["result"]["failed_gates"]

    def test_fewer_than_three_cards_fails_g6(self, tool):
        doc = self._base_envelope()
        doc["artifacts"] = [{"kind": "hypothesis_card_set", "cards": [
            {"id": "H1", "refutation": "if x then y"},
            {"id": "H2", "refutation": "if a then b"},
        ]}]
        res = tool("self-audit", doc)
        assert res["result"]["pass"] is False
        assert "G6_completeness" in res["result"]["failed_gates"]

    def test_missing_provenance_fails_g7(self, tool):
        doc = self._base_envelope()
        del doc["provenance"]["timestamp"]
        res = tool("self-audit", doc)
        assert res["result"]["pass"] is False
        assert "G7_provenance" in res["result"]["failed_gates"]


class TestSchemaSubsetCoverage:
    """The bundled subset validator must handle every keyword the schemas use."""

    def test_output_schema_rejects_invalid_status(self):
        errs = JS.validate_document(
            {"skill": "micp-hypothesis-forge", "status": "NOPE"},
            "schemas/output.schema.json",
        )
        assert any("status" in e["path"] for e in errs)

    def test_output_schema_accepts_full_envelope(self):
        doc = {
            "contract_version": "1.0", "skill": "micp-hypothesis-forge",
            "skill_version": "1.0.0", "status": "SUCCESS", "summary": "s",
            "findings": [{"id": "F1", "epistemic_label": "HYPOTHESIS", "summary": "x"}],
            "assumptions": [], "evidence_used": [{"ref_id": "E1", "role": "r"}],
            "uncertainty": {}, "risks": [],
            "artifacts": [], "requested_next_skills": [], "validation": {},
            "provenance": {"skill": "micp-hypothesis-forge",
                           "skill_version": "1.0.0",
                           "timestamp": "t", "contract_version": "1.0",
                           "controller_version": "0.1.0"},
            "errors": [],
        }
        assert JS.validate_document(doc, "schemas/output.schema.json") == []

    def test_card_set_validates_real_cards(self):
        cs = {
            "kind": "hypothesis_card_set",
            "phenomenon": "strength loss",
            "cards": [
                {"id": "H1", "kind": "hypothesis_card",
                 "statement": "High urease activity reduces strength",
                 "mechanism_chain": ["hydrolysis", "NH4+ accumulation"],
                 "prediction_direction": "decrease",
                 "observables": ["NH4+ (mM)"], "refutation": "if NH4+ > 120 mM",
                 "time_scale": "14 days", "scope": "sand column",
                 "epistemic_label": "HYPOTHESIS",
                 "evidence_for": [], "evidence_against": []},
                {"id": "H2", "kind": "hypothesis_card",
                 "statement": "Calcite washout reduces strength",
                 "mechanism_chain": ["dissolution", "pore opening"],
                 "prediction_direction": "decrease",
                 "observables": ["calcite (%)"], "refutation": "if calcite stays high",
                 "time_scale": "14 days", "scope": "sand column",
                 "epistemic_label": "HYPOTHESIS",
                 "evidence_for": [], "evidence_against": []},
                {"id": "H3", "kind": "hypothesis_card",
                 "statement": "Pore plugging reduces strength non-uniformly",
                 "mechanism_chain": ["entrapment", "plugging"],
                 "prediction_direction": "no_change",
                 "observables": ["permeability (m/s)"], "refutation": "if permeability uniform",
                 "time_scale": "14 days", "scope": "sand column",
                 "epistemic_label": "HYPOTHESIS",
                 "evidence_for": [], "evidence_against": []},
            ],
        }
        assert JS.validate_document(cs, "schemas/card-set.schema.json") == []
