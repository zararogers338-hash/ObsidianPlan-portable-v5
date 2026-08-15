"""Evaluation metrics for obsidian-red-team (M1–M7).

Pure functions over collected per-case results.
"""

from __future__ import annotations

from typing import Any


def structured_output_pass_rate(results: list[dict]) -> float:
    """M1: outputs that passed output.schema.json / output-validation."""
    checked = [r for r in results if r.get("output_validated") is not None]
    if not checked:
        return 0.0
    return sum(1 for r in checked if r["output_validated"]) / len(checked)


def tool_invocation_rate(results: list[dict]) -> float:
    """M2: every case ran the real CLI."""
    return sum(1 for r in results if r.get("tool_ran")) / max(1, len(results))


def evidence_traceability_rate(results: list[dict]) -> float:
    """M3: evidence_used ref_ids in outputs exist in input refs."""
    total, hit = 0, 0
    for r in results:
        for ref_id in r.get("evidence_used", []):
            total += 1
            if ref_id in r.get("input_ref_ids", set()):
                hit += 1
    return hit / max(1, total)


def missing_input_detection_rate(results: list[dict]) -> float:
    """M4: missing-required-field cases produced BLOCKED / ORT-E### with guidance."""
    missing_cases = [r for r in results if r.get("kind") == "missing"]
    if not missing_cases:
        return 1.0
    return sum(1 for r in missing_cases if r.get("detected_missing")) / len(missing_cases)


def adversarial_interception_rate(results: list[dict]) -> float:
    """M5: engineered BLOCKING cases were intercepted (BLOCKING detected)."""
    adversarial = [r for r in results if r.get("kind") == "adversarial"]
    if not adversarial:
        return 1.0
    return sum(1 for r in adversarial if r.get("intercepted")) / len(adversarial)


def repeat_run_consistency(results: list[dict]) -> float:
    """M6: two runs byte-identical on findings + state_recommendation."""
    if not results:
        return 1.0
    return sum(1 for r in results if r.get("repeat_consistent")) / len(results)


def mean_failure_recovery_time(results: list[dict]) -> dict[str, float]:
    """M7: wall time per case; reported as max and mean."""
    times = [r.get("wall_time_ms", 0) for r in results]
    return {"mean_ms": round(sum(times) / max(1, len(times)), 1),
            "max_ms": max(times) if times else 0.0}


def all_metrics(results: list[dict]) -> dict[str, Any]:
    return {
        "M1_structured_output_pass_rate": round(structured_output_pass_rate(results), 3),
        "M2_tool_invocation_rate": round(tool_invocation_rate(results), 3),
        "M3_evidence_traceability_rate": round(evidence_traceability_rate(results), 3),
        "M4_missing_input_detection_rate": round(missing_input_detection_rate(results), 3),
        "M5_adversarial_interception_rate": round(adversarial_interception_rate(results), 3),
        "M6_repeat_run_consistency": round(repeat_run_consistency(results), 3),
        "M7_mean_failure_recovery_time": mean_failure_recovery_time(results),
    }


def thresholds() -> dict[str, float]:
    return {
        "M1_structured_output_pass_rate": 0.95,
        "M2_tool_invocation_rate": 1.0,
        "M3_evidence_traceability_rate": 0.9,
        "M4_missing_input_detection_rate": 1.0,
        "M5_adversarial_interception_rate": 1.0,
        "M6_repeat_run_consistency": 1.0,
    }
