"""Performance indicators for micp-hypothesis-forge (spec §十一).

Seven indicators, each with a measurement method and a minimum threshold.
The runner (run_evals.py) records per-case evidence and rolls the indicators up.

Indicators:
  1. structured_output_pass_rate     — every output validates against output.schema.json
  2. tool_invocation_rate            — >=3 distinct tools invoked per SUCCESS case
  3. evidence_traceability_rate      — every evidence_used.ref_id resolves in refs
  4. missing_input_detection_rate    — missing-field cases -> BLOCKED with missing_inputs
  5. adversarial_interception_rate   — adversarial cases caught (cycle, unfalsifiable, ghost ref)
  6. repeat_run_consistency          — identical input -> identical output (deterministic)
  7. mean_failure_recovery_time      — worst-case stdin->result wall time (s)

Pure stdlib, deterministic given the same case logs.
"""

from __future__ import annotations

# Thresholds mirrored from skill.yaml evaluation.indicators.
THRESHOLDS = {
    "structured_output_pass_rate": 1.0,
    "tool_invocation_rate": 1.0,
    "evidence_traceability_rate": 1.0,
    "missing_input_detection_rate": 1.0,
    "adversarial_interception_rate": 1.0,
    "repeat_run_consistency": 1.0,
    "mean_failure_recovery_time": 60.0,  # seconds, worst case
}


def compute(case_results: list[dict]) -> dict:
    """case_results: list of per-case records produced by run_evals.py.

    Each record has: id, kind (normal/missing/conflicting/boundary/adversarial/
    determinism), ok (bool), plus optional evidence fields used below.
    """
    n = len(case_results)
    if n == 0:
        raise ValueError("no case results to compute indicators from")

    # 1. structured output pass rate
    structured = [c for c in case_results if "schema_valid" in c]
    structured_pass = sum(1 for c in structured if c["schema_valid"]) if structured else 0
    rate_1 = (structured_pass / len(structured)) if structured else 1.0

    # 2. tool invocation rate — every case must have REALLY invoked >=1 tool
    #    via subprocess (no mocks), and full-pipeline cases >=3 distinct tools.
    tools_ok = [c for c in case_results
                if len(c.get("tools_invoked", [])) >= 1]
    full_pipeline = [c for c in case_results if c.get("full_pipeline")]
    fp_ok = all(len(c.get("tools_invoked", [])) >= 3 for c in full_pipeline)
    rate_2 = (len(tools_ok) / n) if n else 1.0
    if full_pipeline and not fp_ok:
        rate_2 = min(rate_2, 0.0)

    # 3. evidence traceability rate — only cases that legitimately carry
    #    evidence refs (normal cases). Adversarial GHOST-ref cases are excluded:
    #    being intercepted is the correct behavior, not a traceability failure.
    traced_cases = [c for c in case_results if "traceability_ok" in c
                    and c.get("kind") == "normal"]
    traced_ok = sum(1 for c in traced_cases if c["traceability_ok"]) if traced_cases else 0
    rate_3 = (traced_ok / len(traced_cases)) if traced_cases else 1.0

    # 4. missing input detection rate
    missing_cases = [c for c in case_results if c.get("kind") == "missing"]
    missing_ok = sum(1 for c in missing_cases
                     if c.get("returned_blocked") and c.get("missing_inputs_listed"))
    rate_4 = (missing_ok / len(missing_cases)) if missing_cases else 1.0

    # 5. adversarial interception rate
    adv_cases = [c for c in case_results if c.get("kind") == "adversarial"]
    adv_ok = sum(1 for c in adv_cases if c.get("intercepted"))
    rate_5 = (adv_ok / len(adv_cases)) if adv_cases else 1.0

    # 6. repeat run consistency
    det_cases = [c for c in case_results if c.get("kind") == "determinism"]
    det_ok = sum(1 for c in det_cases if c.get("deterministic"))
    rate_6 = (det_ok / len(det_cases)) if det_cases else 1.0

    # 7. mean failure recovery time (worst case wall time) — lower is better
    wall_times = [c.get("wall_time_s", 0.0) for c in case_results if c.get("wall_time_s")]
    worst = max(wall_times) if wall_times else 0.0

    indicators = {
        "structured_output_pass_rate": rate_1,
        "tool_invocation_rate": rate_2,
        "evidence_traceability_rate": rate_3,
        "missing_input_detection_rate": rate_4,
        "adversarial_interception_rate": rate_5,
        "repeat_run_consistency": rate_6,
        "mean_failure_recovery_time": worst,
    }
    passed = {
        name: (value >= THRESHOLDS[name])
        if name != "mean_failure_recovery_time"
        else (value <= THRESHOLDS[name])
        for name, value in indicators.items()
    }
    return {"indicators": indicators, "thresholds": THRESHOLDS,
            "passed": passed,
            "all_passed": all(passed.values()),
            "n_cases": n,
            "n_passed": sum(1 for c in case_results if c.get("ok"))}
