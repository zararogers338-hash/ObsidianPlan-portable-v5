"""Integration tests: the full tool pipeline on realistic MICP scenarios."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import run_tool


def _three_hypotheses():
    """Three genuinely competing mechanisms for the inlet-clogging observation."""
    return [
        {"id": "H1",
         "statement": "Inlet clogs by chemical precipitation of calcite",
         "refutation": "If inlet calcite mass increases while inlet cell mass "
                       "stays low, chemical precipitation drives the clog",
         "observables": ["inlet calcite (g)", "inlet cell mass (g)",
                         "pressure rise (kPa)"],
         "observable_predictions": {"inlet calcite (g)": "increase",
                                    "inlet cell mass (g)": "no_change",
                                    "pressure rise (kPa)": "increase"},
         "epistemic_label": "HYPOTHESIS"},
        {"id": "H2",
         "statement": "Inlet clogs by cell entrapment / biofilm accumulation",
         "refutation": "If inlet cell mass increases while inlet calcite stays "
                       "low, cell entrapment drives the clog",
         "observables": ["inlet cell mass (g)", "inlet calcite (g)",
                         "pressure rise (kPa)"],
         "observable_predictions": {"inlet cell mass (g)": "increase",
                                    "inlet calcite (g)": "no_change",
                                    "pressure rise (kPa)": "increase"},
         "epistemic_label": "HYPOTHESIS"},
        {"id": "H3",
         "statement": "Inlet clogs by flow-field redistribution concentrating "
                      "precipitation downstream",
         "refutation": "If downstream calcite increases while inlet pressure "
                       "stays flat, flow-field redistribution drives the clog",
         "observables": ["downstream calcite (g)", "inlet pressure (kPa)"],
         "observable_predictions": {"downstream calcite (g)": "increase",
                                    "inlet pressure (kPa)": "no_change"},
         "epistemic_label": "HYPOTHESIS"},
    ]


class TestPipeline:
    def test_dag_then_scoring_pipeline(self, tool):
        # Mechanism DAG for H1's chain
        dag = tool("dag", {"mechanism_chain": [
            "high urease activity", "accelerated hydrolysis",
            "NH4+ accumulation", "reduced cementation strength",
        ]})
        assert dag["ok"] is True
        assert dag["result"]["acyclic"] is True
        assert dag["result"]["topological_order"][0] == "high urease activity"

        # Score the three cards
        scoring = tool("scoring", {"statements": [
            {"id": "H1", "statement": "High urease activity reduces strength",
             "refutation": "If NH4+ exceeds 120 mM, UCS declines below baseline",
             "observables": ["NH4+ (mM)", "UCS (MPa)"],
             "time_scale": "14 days", "scope": "sand column, 1 M cementation"},
            {"id": "H2", "statement": "Calcite washout reduces strength",
             "refutation": "If calcite content stays high while UCS declines, H2 weakens",
             "observables": ["calcite (%)", "UCS (MPa)"],
             "time_scale": "14 days", "scope": "sand column"},
            {"id": "H3", "statement": "Pore plugging reduces strength non-uniformly",
             "refutation": "If permeability stays uniform while UCS declines, H3 weakens",
             "observables": ["permeability (m/s)", "UCS (MPa)"],
             "time_scale": "14 days", "scope": "sand column"},
        ]})
        assert scoring["ok"] is True
        results = scoring["result"]["results"]
        assert len(results) == 3
        assert all(r["overall"] >= 0.0 for r in results)
        # H1 has a numeric threshold (fully falsifiable); H2/H3 hedge with
        # "stays high"/"stays uniform" (partially falsifiable) — both are
        # admissible, but nothing may be genuinely unfalsifiable.
        verdicts = [r["falsifiability"]["verdict"] for r in results]
        assert "NOT_FALSIFIABLE" not in verdicts
        # The summary field counts anything short of fully falsifiable.
        assert scoring["result"]["summary"]["n_non_falsifiable"] == sum(
            1 for r in results if r["falsifiability"]["verdict"] != "FALSIFIABLE")

    def test_competing_matrix_distinguishes_all_pairs(self, tool):
        res = tool("competing-matrix", {"hypotheses": _three_hypotheses()})
        assert res["ok"] is True
        pairs = res["result"]["pair_discrimination"]
        assert len(pairs) == 3
        for p in pairs:
            assert p["uniquely_discriminable"] is True, f"{p['pair']} not discriminated"
            assert p["best_information_gain_bits"] > 0.0

    def test_experiment_priority_ranks_by_gain(self, tool):
        res = tool("experiment-priority", {"experiments": [
            {"id": "E1", "information_gain_bits": 0.2, "cost_rank": 1,
             "risk_level": "low", "time_scale_days": 3, "feasibility": 0.9},
            {"id": "E2", "information_gain_bits": 0.8, "cost_rank": 2,
             "risk_level": "low", "time_scale_days": 7, "feasibility": 0.8},
            {"id": "E3", "information_gain_bits": 0.5, "cost_rank": 3,
             "risk_level": "high", "time_scale_days": 21, "feasibility": 0.6},
        ]})
        assert res["ok"] is True
        ranked = res["result"]["ranked_experiments"]
        assert ranked[0]["id"] == "E2"  # highest gain, moderate cost, low risk

    def test_card_validate_full_set(self, tool):
        cards = [
            {
                "id": "H1", "kind": "hypothesis_card",
                "statement": "High urease activity reduces strength",
                "premise": "accelerated hydrolysis",
                "mechanism_chain": ["hydrolysis", "NH4+ accumulation"],
                "prediction_direction": "decrease",
                "observables": ["NH4+ (mM)"],
                "refutation": "If NH4+ exceeds 120 mM, UCS declines",
                "time_scale": "14 days",
                "scope": "sand column, 1 M cementation",
                "epistemic_label": "HYPOTHESIS",
                "evidence_for": [{"ref_id": "EV1", "strength": "moderate"}],
                "evidence_against": [],
            },
            {
                "id": "H2", "kind": "hypothesis_card",
                "statement": "Calcite washout reduces strength",
                "premise": "carbonate re-dissolution",
                "mechanism_chain": ["dissolution", "pore opening"],
                "prediction_direction": "decrease",
                "observables": ["calcite (%)"],
                "refutation": "If calcite stays high while UCS declines, H2 weakens",
                "time_scale": "14 days",
                "scope": "sand column",
                "epistemic_label": "HYPOTHESIS",
                "evidence_for": [], "evidence_against": [],
            },
            {
                "id": "H3", "kind": "hypothesis_card",
                "statement": "Pore plugging reduces strength non-uniformly",
                "premise": "cell retention at inlet",
                "mechanism_chain": ["entrapment", "plugging"],
                "prediction_direction": "no_change",
                "observables": ["permeability (m/s)"],
                "refutation": "If permeability stays uniform while UCS declines, H3 weakens",
                "time_scale": "14 days",
                "scope": "sand column",
                "epistemic_label": "HYPOTHESIS",
                "evidence_for": [], "evidence_against": [],
            },
        ]
        res = tool("card-validate", {
            "schema": "schemas/card-set.schema.json",
            "document": {"kind": "hypothesis_card_set",
                         "phenomenon": "strength loss",
                         "cards": cards},
        })
        assert res["ok"] is True
        assert res["result"]["valid"] is True
        assert res["result"]["audit_pass"] is True

    def test_self_audit_full_envelope_passes(self, tool):
        doc = {
            "contract_version": "1.0",
            "skill": "micp-hypothesis-forge",
            "skill_version": "1.0.0",
            "status": "SUCCESS",
            "summary": "Three competing mechanisms forged for inlet clogging.",
            "findings": [
                {"id": "F1", "epistemic_label": "HYPOTHESIS",
                 "summary": "Chemical precipitation is a candidate inlet-clog driver"},
            ],
            "assumptions": [{"id": "A1", "statement": "cementation solution is Ca-rich"}],
            "evidence_used": [{"ref_id": "EV1", "role": "support"}],
            "evidence_refs": [{"ref_id": "EV1"}],
            "uncertainty": {"direction_inference": "keyword-based"},
            "risks": [{"id": "R1", "epistemic_label": "HYPOTHESIS",
                       "risk": "chemical and biological clogging may co-occur"}],
            "artifacts": [
                {"kind": "hypothesis_card_set", "cards": [
                    {"id": "H1", "refutation": "if inlet calcite increases while cells stay low"},
                    {"id": "H2", "refutation": "if inlet cells increase while calcite stays low"},
                    {"id": "H3", "refutation": "if downstream calcite increases while inlet pressure stays flat"},
                ]},
            ],
            "requested_next_skills": [
                {"skill": "obsidian-experiment-designer",
                 "inputs_needed": ["discriminating_matrix"],
                 "reason": "turn ranked experiments into a concrete design"},
            ],
            "validation": {"gates": "G1-G7"},
            "provenance": {
                "skill": "micp-hypothesis-forge",
                "skill_version": "1.0.0",
                "timestamp": "2026-08-06T00:00:00Z",
                "contract_version": "1.0",
                "controller_version": "0.1.0",
            },
            "errors": [],
        }
        res = tool("self-audit", doc)
        assert res["ok"] is True
        assert res["result"]["pass"] is True
