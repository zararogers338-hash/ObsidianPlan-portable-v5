"""Run the full evaluation suite (15 adversarial cases) and assert M1–M7 pass."""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS_DIR = os.path.join(os.path.dirname(HERE), "evals")
sys.path.insert(0, EVALS_DIR)


def test_all_evals_pass():
    import run_evals
    import metrics as metrics_mod

    results, _ = run_evals.run_all()
    metrics = metrics_mod.all_metrics(results)
    thr = metrics_mod.thresholds()

    for metric, value in metrics.items():
        if isinstance(value, dict):
            continue
        assert value >= thr[metric], (
            f"{metric} = {value} < threshold {thr[metric]}"
        )

    # Every engineered-blocking case was intercepted.
    for case in results:
        if run_evals.ADVERSARIAL_EXPECT_BLOCKING.get(case["case"], True):
            assert case["intercepted"], (
                f"{case['case']} engineered as BLOCKING but not intercepted"
            )


def test_all_cases_are_repeat_consistent():
    import run_evals

    results, _ = run_evals.run_all()
    for case in results:
        assert case["repeat_consistent"] is True, f"{case['case']} is not deterministic"
