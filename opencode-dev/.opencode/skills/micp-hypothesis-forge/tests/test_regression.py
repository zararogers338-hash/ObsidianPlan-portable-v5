"""Regression tests: lock in the bugs fixed during self-testing so they never
recur. Each test pins a specific defect that was found while running the skill
for real."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import run_tool


class TestRegressionDag:
    def test_flat_list_chain_is_single_chain(self, tool):
        """Regression: a flat-list mechanism_chain was parsed as N single-step
        chains and rejected. It must be treated as ONE chain."""
        res = tool("dag", {"mechanism_chain": [
            "high urease activity", "accelerated hydrolysis",
            "NH4+ accumulation", "reduced cementation",
        ]})
        assert res["ok"] is True
        assert res["result"]["node_count"] == 4
        assert res["result"]["edge_count"] == 3

    def test_cycle_detected_when_edges_attached(self, tool):
        """Regression: cycles were missed because depends_on was never attached
        to nodes. A->B->C->A must be rejected with MHX-E105."""
        res = tool("dag", {"chains": [["A", "B"], ["B", "C"], ["C", "A"]]})
        assert res["ok"] is False
        assert res["error"]["code"] == "MHX-E105"

    def test_ancestry_is_transitive(self, tool):
        """Regression: ancestry was empty because edges were invisible to the
        closure walker."""
        res = tool("dag", {"mechanism_chain": [
            "high urease activity", "accelerated hydrolysis",
            "NH4+ accumulation", "reduced cementation",
        ]})
        assert res["ok"] is True
        acc = res["result"]["ancestry"]["reduced cementation"]
        assert set(acc["ancestors"]) == {
            "high urease activity", "accelerated hydrolysis", "NH4+ accumulation",
        }


class TestRegressionSchemaPath:
    def test_schema_resolves_from_skill_root(self, tool):
        """Regression: jsonschema SKILL_ROOT pointed one level too high, so
        schema files were 'not found'. Validating must succeed from any cwd."""
        # Run with cwd = temp dir to prove schema resolution is path-safe.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            proc = __import__("subprocess").run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "card-validate.py")],
                input=json.dumps({
                    "schema": "schemas/hypothesis-card.schema.json",
                    "document": {
                        "id": "H1", "kind": "hypothesis_card",
                        "statement": "High urease activity reduces strength",
                        "mechanism_chain": ["hydrolysis", "NH4+ accumulation"],
                        "prediction_direction": "decrease",
                        "observables": ["NH4+ (mM)"],
                        "refutation": "If NH4+ exceeds 120 mM, UCS declines",
                        "time_scale": "14 days", "scope": "sand column",
                        "epistemic_label": "HYPOTHESIS",
                        "evidence_for": [], "evidence_against": [],
                    },
                }),
                capture_output=True, text=True, cwd=tmp,
            )
            env = json.loads(proc.stdout)
            assert env["ok"] is True
            assert env["result"]["valid"] is True


class TestRegressionCompetingMatrix:
    def test_per_observable_predictions_override_text(self, tool):
        """Regression: direction inference was whole-text; per-observable
        predictions (increase vs no_change on the SAME card) were impossible.
        Explicit observable_predictions must win."""
        res = tool("competing-matrix", {"hypotheses": [
            {"id": "H1", "statement": "chemical precipitation",
             "refutation": "if inlet calcite increases while cells stay low",
             "observables": ["calcite (g)", "cell (g)"],
             "observable_predictions": {"calcite (g)": "increase",
                                        "cell (g)": "no_change"}},
            {"id": "H2", "statement": "cell entrapment",
             "refutation": "if cell mass increases while calcite stays low",
             "observables": ["cell (g)", "calcite (g)"],
             "observable_predictions": {"cell (g)": "increase",
                                        "calcite (g)": "no_change"}},
            {"id": "H3", "statement": "flow-field redistribution",
             "refutation": "if downstream calcite increases",
             "observables": ["downstream calcite (g)"],
             "observable_predictions": {"downstream calcite (g)": "increase"}},
        ]})
        assert res["ok"] is True
        dirs = res["result"]["predicted_directions"]
        assert dirs["H1"]["calcite (g)"] == "positive"
        assert dirs["H1"]["cell (g)"] is None       # no_change -> null
        assert dirs["H2"]["cell (g)"] == "positive"
        # All pairs must be uniquely discriminable
        for p in res["result"]["pair_discrimination"]:
            assert p["uniquely_discriminable"] is True

    def test_down_kw_includes_declines(self, tool):
        """Regression: 'declines' was not in the down-keyword list, so strength-
        decline hypotheses produced null directions. A pure-decline statement
        must map to negative. (Phrases mixing 'exceeds'/'accumulation' with
        'declines' are genuinely ambiguous for whole-text inference; use
        observable_predictions to be authoritative — see the test above.)"""
        res = tool("competing-matrix", {"hypotheses": [
            {"id": "H1", "statement": "NH4+ toxicity",
             "refutation": "if NH4+ toxicity is high, UCS declines below baseline",
             "observables": ["UCS (MPa)"]},
            {"id": "H2", "statement": "calcite washout",
             "refutation": "if calcite washes out, UCS declines below baseline",
             "observables": ["UCS (MPa)"]},
            {"id": "H3", "statement": "pore plugging",
             "refutation": "if pores plug, UCS declines below baseline",
             "observables": ["UCS (MPa)"]},
        ]})
        assert res["ok"] is True
        dirs = res["result"]["predicted_directions"]
        assert dirs["H1"]["UCS (MPa)"] == "negative"
        assert dirs["H2"]["UCS (MPa)"] == "negative"
        assert dirs["H3"]["UCS (MPa)"] == "negative"


class TestRegressionSelfAudit:
    def test_gates_have_independent_errors(self, tool):
        """Regression: G1 and G7 shared one errors list, so a G1 failure
        leaked into G7. Each gate must report its own errors."""
        doc = {
            "contract_version": "1.0", "skill": "micp-hypothesis-forge",
            "skill_version": "1.0.0", "status": "BOGUS", "summary": "x",
            "findings": [], "assumptions": [], "evidence_used": [],
            "uncertainty": {}, "risks": [], "artifacts": [],
            "requested_next_skills": [], "validation": {},
            "provenance": {
                "skill": "micp-hypothesis-forge", "skill_version": "1.0.0",
                "timestamp": "t", "contract_version": "1.0",
                "controller_version": "0.1.0",
            },
            "errors": [],
        }
        res = tool("self-audit", doc)
        assert res["ok"] is True
        assert res["result"]["gates"]["G1_envelope"]["ok"] is False
        assert res["result"]["gates"]["G7_provenance"]["ok"] is True
