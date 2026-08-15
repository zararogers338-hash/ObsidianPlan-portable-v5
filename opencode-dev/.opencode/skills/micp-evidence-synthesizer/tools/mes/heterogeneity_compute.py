"""Heterogeneity analysis (OES-E112 guards) + 4-type classification.

Statistical heterogeneity (I2, tau2, Q, prediction interval) is computed by
meta_analyze. This module classifies heterogeneity *type* — statistical vs
methodological vs mechanistic vs scale — from the evidence cards' context
fields, per SKILL.md §能力要求-5 and §验收门槛-4 (冲突不能被平均掩盖).
"""

from __future__ import annotations

from typing import Any, Optional

from .meta_analyze import MetaResult, _inverse_variance_pool
from .unit_map import comparable_unit


def classify_heterogeneity(cards: list[dict], meta: Optional[MetaResult] = None) -> dict:
    """Produce {'statistical': {...}, 'types': [ {type, present, detail} ]}.

    `types` covers all four SKILL.md dimensions; each entry flags whether the
    dimension is a live source of divergence in THIS evidence set.
    """
    types = [
        {"type": "statistical", "present": False, "detail": ""},
        {"type": "methodological", "present": False, "detail": ""},
        {"type": "mechanistic", "present": False, "detail": ""},
        {"type": "scale", "present": False, "detail": ""},
    ]

    # ---- statistical ----
    if meta is not None:
        stat = {
            "i2": meta.i2,
            "tau2": meta.between_study_variance_tau2,
            "q": meta.q,
            "q_p_value": meta.q_p_value,
            "interpretation": _interpret_statistical(meta.i2),
        }
        if meta.i2 is not None and meta.i2 > 25:
            types[0]["present"] = True
            types[0]["detail"] = f"I2={meta.i2:.1f}% (Q p={meta.q_p_value or 0:.3f}) indicates real inter-study variance beyond chance"
    else:
        stat = {"i2": None, "tau2": None, "q": None, "q_p_value": None,
                "interpretation": "no pooling performed — statistical heterogeneity not estimable"}

    # ---- methodological ----
    methods = [c.get("measurement", {}).get("method") if isinstance(c.get("measurement"), dict) else None
               for c in cards]
    methods = [m for m in methods if isinstance(m, str) and m]
    method_detail = _divergence_detail("measurement method", methods)
    if method_detail:
        types[1]["present"] = True
        types[1]["detail"] = method_detail

    stds = [c.get("measurement", {}).get("endpoint_timing") if isinstance(c.get("measurement"), dict) else None
            for c in cards]
    stds = [s for s in stds if isinstance(s, str) and s]
    timing = _divergence_detail("endpoint timing", stds)
    if timing:
        types[1]["detail"] = "; ".join(x for x in (types[1]["detail"], timing) if x)

    # ---- mechanistic ----
    layers = {c.get("layer") for c in cards if isinstance(c.get("layer"), str)}
    if len(layers) > 1:
        types[2]["present"] = True
        types[2]["detail"] = f"cards span multiple MICP layers: {sorted(layers)} — mechanism may differ"
    strains = {s for c in cards for s in (c.get("strain") or []) if isinstance(s, str)}
    if len(strains) > 1:
        types[2]["present"] = True
        types[2]["detail"] = "; ".join(x for x in (types[2]["detail"],
            f"strains differ: {sorted(strains)}") if x)

    # ---- scale ----
    scales = {c.get("context", {}).get("scale") if isinstance(c.get("context"), dict) else None
              for c in cards}
    scales = {s for s in scales if isinstance(s, str) and s}
    if len(scales) > 1:
        types[3]["present"] = True
        types[3]["detail"] = f"scales differ: {sorted(scales)}"

    sample_sizes = [c.get("sample", {}).get("diameter_mm") for c in cards
                    if isinstance(c.get("sample"), dict) and c["sample"].get("diameter_mm") is not None]
    if len(set(sample_sizes)) > 1:
        types[3]["present"] = True
        types[3]["detail"] = "; ".join(x for x in (types[3]["detail"],
            "specimen geometry differs across studies") if x)

    return {"statistical": stat, "types": types}


def _divergence_detail(what: str, values: list[str]) -> str:
    if len(values) <= 1:
        return ""
    unique = sorted({v for v in values})
    if len(unique) == 1:
        return ""
    return f"{what} diverges: {unique}"


def _interpret_statistical(i2: Optional[float]) -> str:
    if i2 is None:
        return "not estimable"
    if i2 < 25:
        return "low heterogeneity"
    if i2 < 50:
        return "moderate heterogeneity"
    if i2 < 75:
        return "substantial heterogeneity"
    return "considerable heterogeneity (pooling discouraged)"


def check_comparability(cards: list[dict]) -> dict:
    """Structural comparability gate across cards (OES-E112).

    Returns {status: comparable|conditional|incomparable|insufficient,
             dimensions: [ {dimension, status, detail} ]}.

    Dimensions: strain, material, grain_size, saturation, concentration, scale,
    injection_protocol, measurement_method, endpoint, units.
    """
    if not cards:
        return {"status": "insufficient", "dimensions": []}
    dims: list[dict] = []
    statuses: list[str] = []

    def _track(name: str, values: list[Any], missing_ok: bool = True,
               normalize=lambda v: v) -> None:
        vals = [normalize(v) for v in values if v is not None and v != ""]
        uniq = sorted({str(v) for v in vals})
        if not vals:
            s = "missing"
            d = f"{name}: not reported in any card"
        elif len(uniq) == 1:
            s = "comparable"
            d = f"{name}: uniform ({uniq[0]})"
        else:
            s = "mixed"
            d = f"{name}: diverges across studies ({', '.join(uniq)})"
        dims.append({"dimension": name, "status": s, "detail": d})
        statuses.append(s)

    _track("strain", [",".join(c.get("strain") or []) for c in cards])
    _track("material", [c.get("material", {}).get("soil_type") if isinstance(c.get("material"), dict) else None
                        for c in cards])
    _track("grain_size", [c.get("material", {}).get("grain_size_d50_mm") if isinstance(c.get("material"), dict)
                          else None for c in cards])
    _track("saturation", [c.get("context", {}).get("saturation") if isinstance(c.get("context"), dict)
                          else None for c in cards])
    _track("concentration", [c.get("treatment", {}).get("cementation_solution_concentration", {}).get("value")
                             if isinstance(c.get("treatment"), dict) and c["treatment"].get("cementation_solution_concentration")
                             else None for c in cards])
    _track("scale", [c.get("context", {}).get("scale") if isinstance(c.get("context"), dict) else None
                     for c in cards])
    _track("injection_protocol", [c.get("treatment", {}).get("injection_protocol")
                                  if isinstance(c.get("treatment"), dict) else None for c in cards])
    _track("measurement_method", [c.get("measurement", {}).get("method")
                                  if isinstance(c.get("measurement"), dict) else None for c in cards])
    _track("endpoint", [c.get("outcome", {}).get("name") if isinstance(c.get("outcome"), dict) else None
                        for c in cards])

    # specimen geometry (scale heterogeneity): diameter + height + loading rate
    _track("specimen_diameter",
           [c.get("sample", {}).get("diameter_mm") if isinstance(c.get("sample"), dict) else None
            for c in cards])
    _track("specimen_height",
           [c.get("sample", {}).get("height_mm") if isinstance(c.get("sample"), dict) else None
            for c in cards])
    _track("loading_rate",
           [c.get("sample", {}).get("loading_rate_mm_min") if isinstance(c.get("sample"), dict) else None
            for c in cards])

    # units across outcome values
    units = [c.get("outcome", {}).get("unit") for c in cards if isinstance(c.get("outcome"), dict)]
    units = [u for u in units if isinstance(u, str) and u]
    if len(units) > 1:
        comparable_pairs = all(comparable_unit(units[0], u) for u in units[1:])
        if comparable_pairs:
            dims.append({"dimension": "units", "status": "comparable",
                         "detail": f"units comparable after normalization: {sorted(set(units))}"})
        else:
            dims.append({"dimension": "units", "status": "incomparable",
                         "detail": f"units NOT comparable: {sorted(set(units))}"})
            statuses.append("incomparable")
    elif len(units) == 1:
        dims.append({"dimension": "units", "status": "comparable", "detail": f"uniform unit {units[0]}"})
        statuses.append("comparable")
    else:
        dims.append({"dimension": "units", "status": "missing", "detail": "no outcome units reported"})
        statuses.append("missing")

    if "incomparable" in statuses:
        overall = "incomparable"
    elif "missing" in statuses and all(s in ("missing", "comparable") for s in statuses):
        overall = "insufficient"
    elif "mixed" in statuses:
        overall = "conditional"
    else:
        overall = "comparable"
    return {"status": overall, "dimensions": dims}
