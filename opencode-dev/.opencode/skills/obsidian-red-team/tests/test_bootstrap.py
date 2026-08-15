"""Regression: the bootstrap loop must surface the strongest methodological
counterexamples (I² precision-confounding, 2-study fixed-effect pooling, GRADE
imprecision without power) when reviewing a meta-analysis methodology claim."""

from __future__ import annotations

import json
import os
import sys

from conftest import run_cli

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT = os.path.join(os.path.dirname(HERE), "evals", "bootstrap")


def _load(name: str) -> dict:
    with open(os.path.join(BOOT, name), encoding="utf-8") as fh:
        return json.load(fh)


class TestBootstrapLoop:
    def test_step1_catches_strongest_counterexamples(self):
        payload = _load("step1-review-evidence-synthesizer.json")
        out = run_cli("review", payload)
        assert out["ok"] is True
        r = out["result"]
        summaries = " ".join(f["summary"] for f in r["findings"])

        # The strongest methodological counterexamples must be present.
        assert "I²" in summaries or "I2" in summaries, "I² precision-confounding missed"
        assert "固定效应" in summaries, "2-study fixed-effect pooling missed"
        assert "GRADE" in summaries, "GRADE imprecision-without-power missed"
        # Epistemic escalation is a genuine BLOCKING here.
        assert any(f["severity"] == "BLOCKING" for f in r["findings"])

    def test_step2_self_review_surfaces_methodology(self):
        payload = _load("step2-self-review.json")
        out = run_cli("review", payload)
        assert out["ok"] is True
        r = out["result"]
        summaries = " ".join(f["summary"] for f in r["findings"])
        assert "I²" in summaries or "I2" in summaries
        assert "固定效应" in summaries

    def test_self_review_never_generic_pass(self):
        # A review with targets that name the strongest counterexample must
        # never come back with zero findings.
        payload = _load("step2-self-review.json")
        out = run_cli("review", payload)
        assert len(out["result"]["findings"]) > 0
