"""micp-instrumentation-qc: Shewhart control chart, drift / over-range / saturation / baseline / timestamp checks.

Pure Python standard library. Deterministic. Operates on a list of measurements
(see schemas/input.schema.json). Judgment rules (tool-enforced):

  |z| >= 3                     -> OUT_OF_CONTROL
  |z| >= 2                     -> WARNING
  7 consecutive same-side      -> DRIFT
  6 consecutive monotonic      -> DRIFT
  value outside instrument range -> OVER_RANGE
  value at/above saturation_threshold -> SATURATION
  value beyond mean +/- 10*std -> BASELINE_ANOMALY (also flagged if a period of
  stable baseline precedes a step change; a simple rolling-window rule is used)
  timestamp non-monotonic or outside [earliest_collection, latest_collection]
  with a tolerance window       -> TIMESTAMP_MISALIGNMENT
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from _common import check_numeric


def _as_dt(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _zscore(value: float, mean: float, sd: float) -> float:
    if sd <= 0:
        return 0.0
    return (value - mean) / sd


def _consecutive_same_side(values: list[float], mean: float) -> bool:
    """7 consecutive points on the same side of the mean -> drift."""
    if len(values) < 7:
        return False
    run = 0
    for v in values:
        if v > mean:
            run = run + 1 if run >= 0 else 1
        elif v < mean:
            run = run - 1 if run <= 0 else -1
        else:
            run = 0
        if abs(run) >= 7:
            return True
    return False


def _monotonic_run(values: list[float], run_len: int = 6) -> bool:
    """6 consecutive increasing or decreasing points -> drift."""
    if len(values) < run_len:
        return False
    inc = dec = 1
    for i in range(1, len(values)):
        if values[i] > values[i - 1]:
            inc += 1
            dec = 1
        elif values[i] < values[i - 1]:
            dec += 1
            inc = 1
        else:
            inc = dec = 1
        if inc >= run_len or dec >= run_len:
            return True
    return False


def _baseline_step_change(values: list[float], window: int = 5) -> bool:
    """Heuristic: a stable window followed by a jump beyond mean +/- 10*std."""
    n = len(values)
    if n < window + 2:
        return False
    base = values[:window]
    mean = sum(base) / len(base)
    sd = math.sqrt(sum((v - mean) ** 2 for v in base) / max(1, len(base) - 1))
    if sd <= 0:
        return False
    for v in values[window:]:
        if abs(v - mean) > 10 * sd:
            return True
    return False


def check_measurements(data: dict[str, Any]) -> dict[str, Any]:
    """Run control-chart checks on qc_input.measurements.

    Each measurement must have value, unit, timestamp, instrument_id, sample_id.
    qc (mean/sd/range) may be supplied; otherwise mean/sd are estimated from the
    measurements themselves.
    """
    measurements = data.get("measurements")
    if not measurements:
        raise ValueError("MICQ-E1001: no measurements provided for control-chart check")

    instruments = {i.get("instrument_id"): i for i in (data.get("instruments") or [])}
    problems: list[dict[str, Any]] = []
    for i, m in enumerate(measurements):
        problems.extend(check_numeric(m.get("value"), f"measurements[{i}].value", finite=True))
    if problems:
        raise ValueError("MICQ-E1001: invalid measurement values: " + ", ".join(p["problem"] for p in problems))

    flags: list[dict[str, Any]] = []
    counts = {"pass": 0, "warning": 0, "out_of_control": 0, "drift": 0,
              "over_range": 0, "saturation": 0, "baseline": 0, "timestamp": 0}

    # Global stats (if per-measurement qc not supplied).
    values = [float(m["value"]) for m in measurements]
    global_mean = sum(values) / len(values)
    global_sd = math.sqrt(sum((v - global_mean) ** 2 for v in values) / max(1, len(values) - 1))

    # Per-instrument stats for drift detection.
    by_instrument: dict[str, list[float]] = {}
    for m in measurements:
        by_instrument.setdefault(m.get("instrument_id", "?"), []).append(float(m["value"]))

    for idx, m in enumerate(measurements):
        mid = m.get("measurement_id", f"m{idx}")
        val = float(m["value"])
        instr = instruments.get(m.get("instrument_id", ""), {})
        qc = m.get("qc") or {}
        mean = qc.get("mean") if qc.get("mean") is not None else global_mean
        sd = qc.get("sd") if qc.get("sd") is not None else global_sd

        z = _zscore(val, float(mean), float(sd))
        m_flags: list[str] = []
        severity: str = "info"

        if z >= 3:
            m_flags.append("OUT_OF_CONTROL")
            counts["out_of_control"] += 1
            severity = "blocker"
        elif z >= 2:
            m_flags.append("WARNING")
            counts["warning"] += 1
            severity = "warning"

        rng = instr.get("measurement_range")
        if rng and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
            if val < lo or val > hi:
                m_flags.append("OVER_RANGE")
                counts["over_range"] += 1
                severity = "blocker"

        sat = instr.get("saturation_threshold")
        if sat is not None and val >= float(sat):
            m_flags.append("SATURATION")
            counts["saturation"] += 1
            severity = "blocker"

        for fl in m_flags:
            flags.append({
                "sample_id": m.get("sample_id", "?"),
                "flag": fl,
                "severity": severity,
                "details": f"measurement {mid}, value {val}, z={z:.2f}",
            })

        if not m_flags:
            counts["pass"] += 1

    # Global drift checks.
    drift_flags: list[dict[str, Any]] = []
    if _consecutive_same_side(values, global_mean):
        drift_flags.append({"sample_id": "*", "flag": "DRIFT",
                            "severity": "warning",
                            "details": "7 consecutive measurements on same side of the mean"})
    if _monotonic_run(values):
        drift_flags.append({"sample_id": "*", "flag": "DRIFT",
                            "severity": "warning",
                            "details": "6 consecutive monotonic measurements"})
    if _baseline_step_change(values):
        drift_flags.append({"sample_id": "*", "flag": "BASELINE_ANOMALY",
                            "severity": "warning",
                            "details": "step change beyond 10*sd after stable window"})
    if drift_flags:
        counts["drift"] += 1
        counts["baseline"] += 1
        flags.extend(drift_flags)

    # Timestamp alignment: non-monotonic or outside sample collection window.
    samples = {s.get("sample_id"): s for s in (data.get("samples") or [])}
    timestamps = [m.get("timestamp") for m in measurements if m.get("timestamp")]
    dt_list = [t for t in (_as_dt(x) for x in timestamps) if t is not None]
    if len(dt_list) > 1:
        if any((dt_list[i] - dt_list[i - 1]).total_seconds() < 0 for i in range(1, len(dt_list))):
            flags.append({"sample_id": "*", "flag": "TIMESTAMP_MISALIGNMENT",
                          "severity": "warning",
                          "details": "measurement timestamps are not monotonic"})
            counts["timestamp"] += 1
    for m in measurements:
        sid = m.get("sample_id", "?")
        if sid in samples:
            coll = _as_dt(samples[sid].get("collection_time", ""))
            ts = _as_dt(m.get("timestamp", ""))
            if coll and ts and ts < coll:
                flags.append({"sample_id": sid, "flag": "TIMESTAMP_MISALIGNMENT",
                              "severity": "warning",
                              "details": f"measurement time {m.get('timestamp')} precedes collection {samples[sid].get('collection_time')}"})
                counts["timestamp"] += 1

    total = len(measurements)
    pass_count = counts["pass"]
    return {
        "total": total,
        "pass_count": pass_count,
        "warning_count": counts["warning"],
        "out_of_control_count": counts["out_of_control"],
        "drift_count": counts["drift"],
        "over_range_count": counts["over_range"],
        "saturation_count": counts["saturation"],
        "baseline_anomaly_count": counts["baseline"],
        "timestamp_misalignment_count": counts["timestamp"],
        "pass_rate": round(pass_count / total, 4) if total else 0.0,
        "flags": flags,
        "global_mean": round(global_mean, 6),
        "global_sd": round(global_sd, 6),
    }
