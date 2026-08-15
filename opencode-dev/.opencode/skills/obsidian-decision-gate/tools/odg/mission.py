"""Mission Lock comparator: check success criteria and failure thresholds.

Consumes the Mission Lock contract (metrics with direction + target/threshold,
success_criteria, failure_thresholds) plus the evidence/outcome context and
produces a per-metric verdict. The results feed the gate as:
  - criteria_met / criteria_not_met
  - failure_thresholds_triggered
  - metric statuses (met / not_met / triggered / n/a / unknown)

Success-criteria evaluation is evidence-driven, not model-opinion: each
criterion maps to outcome thresholds in the experiment/evidence context. When
no mapping can be established the criterion is marked not_met with a "why"
explaining exactly what evidence would satisfy it (never a fuzzy pass).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MetricCheck:
    name: str
    direction: str
    current_value: float | None
    target_value: float | None
    threshold_value: float | None
    status: str  # met / not_met / triggered / n/a / unknown
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "threshold_value": self.threshold_value,
            "status": self.status,
            "note": self.note,
        }


@dataclass
class MissionCheck:
    criteria_met: list[str]
    criteria_not_met: list[dict]
    failure_thresholds_triggered: list[dict]
    metrics: list[MetricCheck]

    def to_dict(self) -> dict:
        return {
            "criteria_met": self.criteria_met,
            "criteria_not_met": self.criteria_not_met,
            "failure_thresholds_triggered": self.failure_thresholds_triggered,
            "metrics": [m.to_dict() for m in self.metrics],
        }


def _outcome_values(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map outcome name -> {value, threshold, direction, status, unit}."""
    out: dict[str, dict[str, Any]] = {}
    for e in payload.get("experiment_results", []) or []:
        for o in e.get("outcomes", []) or []:
            name = o.get("name")
            if not name:
                continue
            v = o.get("value")
            if v is None:
                continue
            out[name] = {
                "value": float(v),
                "threshold": o.get("threshold"),
                "direction": o.get("direction", "maximize"),
                "status": o.get("status"),
                "unit": o.get("unit", ""),
            }
    return out


def _metric_against_current(metric: dict, current: dict) -> MetricCheck:
    name = metric.get("name", "?")
    direction = metric.get("direction", "maximize")
    cur = metric.get("current") or {}
    target = metric.get("target") or {}
    threshold = metric.get("threshold") or {}
    cval = cur.get("value")
    tval = target.get("value")
    thval = threshold.get("value")
    tolerance = target.get("error_bars", 0.0)

    if cval is None:
        return MetricCheck(name, direction, None, tval, thval, "unknown",
                           "no measured current value in evidence context")

    status = "n/a"
    note: str = ""
    if direction == "maximize":
        if tval is not None:
            if cval + tolerance >= tval:
                status = "met"
            else:
                status = "not_met"
                note = f"current {cval} < target {tval} (tolerance {tolerance})"
        elif thval is not None and cval < thval:
            status = "not_met"
            note = f"current {cval} below threshold {thval}"
        else:
            status = "unknown"
            note = "no target/threshold declared for maximize metric"
    elif direction == "minimize":
        if tval is not None:
            if cval - tolerance <= tval:
                status = "met"
            else:
                status = "not_met"
                note = f"current {cval} > target {tval} (tolerance {tolerance})"
        elif thval is not None and cval > thval:
            status = "not_met"
            note = f"current {cval} above threshold {thval}"
        else:
            status = "unknown"
            note = "no target/threshold declared for minimize metric"
    elif direction == "maintain":
        if tval is not None and abs(cval - tval) <= max(tolerance, 0.05 * abs(tval)):
            status = "met"
        elif tval is not None:
            status = "not_met"
            note = f"current {cval} drifted from target {tval}"
        else:
            status = "unknown"
    return MetricCheck(name, direction, cval, tval, thval, status, note)


def _metric_against_outcome(metric: dict, outcome: dict) -> MetricCheck:
    name = metric.get("name", "?")
    direction = metric.get("direction", "maximize")
    cval = float(outcome["value"])
    threshold = outcome.get("threshold")
    odir = outcome.get("direction", "maximize")
    ost = outcome.get("status")

    status = "unknown"
    note = ""
    if ost == "met":
        status = "met"
    elif ost == "not_met":
        status = "not_met"
    elif threshold is not None:
        ok = (cval >= float(threshold)) if odir == "maximize" else (cval <= float(threshold))
        status = "met" if ok else "not_met"
        if not ok:
            note = f"outcome {name} = {cval} vs threshold {threshold}"
    else:
        note = "no threshold declared on outcome; infer from mission metric"
    return MetricCheck(name, direction, cval, None, float(threshold) if threshold is not None else None, status, note)


def check_mission(payload: dict[str, Any]) -> MissionCheck:
    mission = payload.get("mission_lock") or {}
    metrics = mission.get("metrics", []) or []
    outcomes = _outcome_values(payload)

    metric_checks: list[MetricCheck] = []
    for m in metrics:
        # prefer direct evidence outcome by name match
        direct = outcomes.get(m.get("name"))
        if direct is not None:
            metric_checks.append(_metric_against_outcome(m, direct))
        else:
            # fall back to the metric's own declared current value
            metric_checks.append(_metric_against_current(m, m.get("current") or {}))

    # success criteria: match each criterion to a metric or, failing that, to
    # an evidence outcome whose name/keywords appear in the criterion text.
    # If none of the bearing metrics is "met", the criterion is not_met with a why.
    def _criterion_bearing(criterion: str) -> list[MetricCheck]:
        """Metrics + outcome-derived checks that bear on this criterion."""
        bearing = [mc for mc in metric_checks if mc.name.lower() in criterion.lower() or criterion.lower() in mc.name.lower()]
        if bearing:
            return bearing
        # outcome-name synonym match (Chinese ↔ English domains)
        SYNS = {
            "strength": ["强度", "抗压", "固结", "承载"],
            "ammonia": ["氨", "nh3", "氨排放", "铵"],
            "permeability": ["渗透", "渗透系数", "水力"],
            "calcite": ["方解石", "碳酸钙", "矿物"],
            "urea": ["尿素", "水解"],
            "urease": ["脲酶", "酶活"],
        }
        hits = []
        for oname, ov in outcomes.items():
            oname_l = oname.lower()
            if oname_l in criterion.lower() or criterion.lower() in oname_l:
                hits.append(_metric_against_outcome(
                    {"name": oname, "direction": ov.get("direction", "maximize")}, ov))
                continue
            # synonym family match: an outcome binds to the criterion only when
            # the criterion mentions one of THAT outcome's own domain keywords.
            # ("强度≥5MPa" binds strength; it must never bind ammonia_emission.)
            own_family = next((syns for root, syns in SYNS.items() if oname_l.startswith(root)), None)
            if own_family and any(syn and syn in criterion for syn in own_family):
                hits.append(_metric_against_outcome(
                    {"name": oname, "direction": ov.get("direction", "maximize")}, ov))
        if hits:
            return hits
        # unit + number heuristic: criterion text carries "5 MPa"/"5MPa" and an
        # outcome exists whose unit matches → threshold-check the extracted number.
        import re as _re
        unit = None
        num = None
        m = _re.search(r"(\d+(?:\.\d+)?)\s*(MPa|kPa|g/L|mg/L|mg/m³|kg/m³|mm|%|℃|°C)", criterion)
        if m:
            num = float(m.group(1))
            unit = m.group(2)
        if num is not None and unit:
            for oname, ov in outcomes.items():
                ounit = str(ov.get("unit", ""))
                if ounit and ounit.lower().replace(" ", "") == unit.lower():
                    threshold = num
                    odir = ov.get("direction", "maximize")
                    cval = float(ov["value"])
                    ok = (cval >= threshold) if odir == "maximize" else (cval <= threshold)
                    status = "met" if ok else "not_met"
                    hits.append(MetricCheck(
                        oname, odir, cval, threshold, threshold, status,
                        note=f"criterion-extracted threshold {threshold} {unit}"))
        return hits

    criteria_met: list[str] = []
    criteria_not_met: list[dict] = []
    for c in mission.get("success_criteria", []) or []:
        bearing = _criterion_bearing(c)
        if bearing and all(mc.status in ("met", "n/a") for mc in bearing):
            criteria_met.append(c)
        elif bearing:
            unmet = [mc.name for mc in bearing if mc.status == "not_met"]
            criteria_not_met.append({
                "criterion": c,
                "why": f"相关指标未达标: {', '.join(unmet) or 'unknown status'}",
            })
        else:
            # no metric mapping: mark not_met with the evidence needed
            criteria_not_met.append({
                "criterion": c,
                "why": "未找到对应指标/结果证据；需提供 outcome 或指标当前值以判定达标",
            })

    failure_thresholds_triggered: list[dict] = []
    for ft in mission.get("failure_thresholds", []) or []:
        # direct mapping: an outcome whose name appears in the threshold text
        hit = outcomes.get(ft)
        if hit is not None:
            failure_thresholds_triggered.append({
                "threshold": ft,
                "why": f"outcome {ft} present (value={hit['value']})",
            })
            continue
        bearing = [mc for mc in metric_checks if mc.status == "triggered"]
        if bearing:
            failure_thresholds_triggered.append({
                "threshold": ft,
                "why": f"相关指标触发: {', '.join(mc.name for mc in bearing)}",
            })

    # honor explicit failure-threshold declarations carried by the payload
    for ft in (payload.get("failure_thresholds_triggered") or []):
        if ft not in [t["threshold"] for t in failure_thresholds_triggered]:
            failure_thresholds_triggered.append({"threshold": ft, "why": "输入声明的失败阈值"})

    return MissionCheck(criteria_met, criteria_not_met, failure_thresholds_triggered, metric_checks)
