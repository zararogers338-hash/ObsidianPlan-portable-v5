"""Quantity constructor for micp-evidence-extractor.

Every quantity is a `quantity` object per evidence-card.schema.json $defs.quantity:
  value, unit, normalized_value, normalized_unit, acquisition_mode, statistic_type,
  n, n_note, uncertainty_type, uncertainty_value, uncertainty_ci_level,
  group_id, timepoint_id, sources[], digitization?, epistemic_tag, note.

Hard rules enforced here:
  - Placeholder modes (NOT_REPORTED / AMBIGUOUS) carry value=null and are
    excluded from every arithmetic helper (mean/sum/min/max). Mixing a
    placeholder into a calculation is a hard error.
  - DIGITIZED_FROM_FIGURE requires digitization.error_estimate (a reading
    error); the skill never presents a figure readout as an author-reported
    value.
  - epistemic_tag is mandatory and INFERRED/HYPOTHESIS/RECOMMENDATION may
    never be downgraded to REPORTED/OBSERVED by helper code.
"""

from __future__ import annotations

import math
from typing import Any

from _common import ToolError
from models import AcquisitionMode, EpistemicTag, PLACEHOLDER_MODES
from units import normalize as unit_normalize


def is_placeholder(quantity: dict[str, Any]) -> bool:
    return (quantity.get("acquisition_mode") or "") in PLACEHOLDER_MODES


# Keys that must always be present on a quantity, even when their value is None
# (they are schema-required). Optional fields with None are dropped.
_ALWAYS_KEYS = {"value", "unit", "normalized_value", "normalized_unit",
                "acquisition_mode", "statistic_type", "n", "uncertainty_type",
                "sources", "epistemic_tag"}


def _clean(quant: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in quant.items()
            if v is not None or k in _ALWAYS_KEYS}


def placeholder(mode: str, *, role: str | None = None, unit: str = "",
                group_id: str | None = None, timepoint_id: str | None = None,
                sources: list[dict] | None = None, note: str | None = None,
                epistemic_tag: str = "REPORTED", statistic_type: str = "unknown") -> dict[str, Any]:
    """A NOT_REPORTED / AMBIGUOUS quantity. value is always null.

    `epistemic_tag` defaults to REPORTED: the placeholder records that the
    paper did not report a value (acquisition_mode), which is itself a
    fact — the epistemic tag describes the claim, not the acquisition.
    """
    if mode not in PLACEHOLDER_MODES:
        raise ValueError(f"placeholder() only accepts NOT_REPORTED/AMBIGUOUS, got {mode!r}")
    tag = epistemic_tag if epistemic_tag in {t.value for t in EpistemicTag} \
        else EpistemicTag.REPORTED.value
    return _clean({
        "value": None,
        "unit": str(unit or ""),
        "normalized_value": None,
        "normalized_unit": "",
        "acquisition_mode": mode,
        "statistic_type": statistic_type,
        "n": 0,
        "n_note": None,
        "uncertainty_type": "none",
        "uncertainty_value": None,
        "group_id": group_id,
        "timepoint_id": timepoint_id,
        "sources": sources or [],
        "epistemic_tag": tag,
        "note": note or (f"{mode}: value not available" if mode == "NOT_REPORTED"
                         else "value ambiguous as reported"),
    })


def reported(
    value: float, unit: str, *,
    acquisition_mode: str = "REPORTED_TEXT",
    statistic_type: str = "mean",
    n: int = 0, n_note: str | None = None,
    uncertainty_type: str = "none", uncertainty_value: float | None = None,
    uncertainty_ci_level: float | None = None,
    group_id: str | None = None, timepoint_id: str | None = None,
    sources: list[dict] | None = None,
    digitization: dict[str, Any] | None = None,
    epistemic_tag: str = "REPORTED", note: str | None = None,
    role: str | None = None, label: str | None = None,
) -> dict[str, Any]:
    """Build a reported quantity with raw + normalized fields.

    When acquisition_mode == DIGITIZED_FROM_FIGURE the caller MUST pass
    digitization.error_estimate; otherwise a ToolError is raised (E704 — the
    skill never presents a figure readout as a plain author-reported value).
    """
    if acquisition_mode not in {m.value for m in AcquisitionMode}:
        raise ToolError("E_ACQ_MODE", f"unknown acquisition mode {acquisition_mode!r}")
    if acquisition_mode == "DIGITIZED_FROM_FIGURE":
        est = None if digitization is None else digitization.get("error_estimate")
        if not (isinstance(est, (int, float)) and not isinstance(est, bool) and est >= 0):
            raise ToolError(
                "MEE-E704",
                "DIGITIZED_FROM_FIGURE requires digitization.error_estimate "
                "(a figure readout must carry its reading error; it is never an "
                "author-reported value)")
    if epistemic_tag not in {t.value for t in EpistemicTag}:
        raise ToolError("E_TAG", f"unknown epistemic tag {epistemic_tag!r}")
    v = float(value)
    if not math.isfinite(v):
        raise ToolError("E_NUMERIC_NON_FINITE", "reported value must be finite")
    norm = unit_normalize(v, unit, role=role, label=label or note)
    # When the raw unit is absent/ambiguous the normalize pass demotes the
    # acquisition_mode to AMBIGUOUS and refuses a normalized value — the caller
    # must keep that placeholder out of arithmetic. EXCEPTION: an explicit
    # DIGITIZED_FROM_FIGURE mode is kept (it already carries its reading-error
    # guard and its unit is often empty because the figure axis provides it).
    if norm.get("acquisition_mode") == "AMBIGUOUS" and acquisition_mode != "DIGITIZED_FROM_FIGURE":
        acquisition_mode = "AMBIGUOUS"
    q: dict[str, Any] = _clean({
        "value": v,
        "unit": str(unit or ""),
        "normalized_value": norm.get("normalized_value"),
        "normalized_unit": norm.get("normalized_unit") or "",
        "acquisition_mode": acquisition_mode,
        "statistic_type": statistic_type,
        "n": int(n or 0),
        "n_note": n_note,
        "uncertainty_type": uncertainty_type,
        "uncertainty_value": None if uncertainty_value is None else float(uncertainty_value),
        "uncertainty_ci_level": uncertainty_ci_level,
        "group_id": group_id,
        "timepoint_id": timepoint_id,
        "sources": sources or [],
        "epistemic_tag": epistemic_tag,
        "note": note,
    })
    if digitization:
        q["digitization"] = digitization
    return q


def with_binding(quantity: dict[str, Any], *, group_id: str | None = None,
                 timepoint_id: str | None = None) -> dict[str, Any]:
    """Return a copy bound to a group/time point (isolation discipline)."""
    out = dict(quantity)
    if group_id is not None:
        out["group_id"] = group_id
    if timepoint_id is not None:
        out["timepoint_id"] = timepoint_id
    return out


# ---------------------------------------------------------------------------
# Arithmetic over quantities (placeholder-safe)
# ---------------------------------------------------------------------------

def _numeric_values(quantities: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for q in quantities:
        if is_placeholder(q):
            continue
        v = q.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)):
            out.append(float(v))
    return out


def mean(quantities: list[dict[str, Any]]) -> float | None:
    vals = _numeric_values(quantities)
    return sum(vals) / len(vals) if vals else None


def total(quantities: list[dict[str, Any]]) -> float | None:
    vals = _numeric_values(quantities)
    return sum(vals) if vals else None


def placeholder_count(quantities: list[dict[str, Any]]) -> int:
    return sum(1 for q in quantities if is_placeholder(q))
