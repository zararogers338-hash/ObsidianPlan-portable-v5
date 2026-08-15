"""Regulatory & standard lookup for micp-biosafety-environment-auditor.

Design constraints:
- NEVER fabricates a regulation, a limit value, or a legal conclusion.
- Every record carries: region, name, doc_id (standard number / decree),
  issued_date, status, verified_on, source, and a `verified` flag.
- A record whose `verified` flag is False (or whose verification horizon has
  passed) must be surfaced as REGULATORY_VERIFICATION_REQUIRED, never asserted.
- Lookup failures return `verified=False` with the reason, so callers mark
  REGULATORY_VERIFICATION_REQUIRED and gate approvals.

The embedded database lives in references/regulatory_db/. A curator keeps it
current; this module only reads it. Network access is NOT performed here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import MbsError, MbsErrorCode

_REGULATORY_DB_DIR = Path(__file__).resolve().parent.parent.parent / "references" / "regulatory_db"
# How old (days) a verified record may be before it is treated as stale.
MAX_REG_RECORD_AGE_DAYS = 365

# Fields a regulation record is required to carry.
REQUIRED_REG_FIELDS = ["id", "region", "name", "doc_id", "issued_date", "status", "source"]


def _load_regulation(record_id: str) -> dict[str, Any] | None:
    """Load a single regulation record from the local db (no network)."""
    path = _REGULATORY_DB_DIR / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MbsError(
            MbsErrorCode.CONTEXT_CORRUPT,
            f"Regulatory record unreadable: {path}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
    for f in REQUIRED_REG_FIELDS:
        if f not in data:
            raise MbsError(
                MbsErrorCode.CONTEXT_CORRUPT,
                f"Regulatory record '{record_id}' missing required field '{f}'.",
                detail={"record": record_id, "field": f},
            )
    return data


def _now_epoch_days() -> int:
    import time

    return int(time.time() / 86400)


def _parse_iso_date(value: str) -> int:
    """Return epoch days for an ISO date (YYYY-MM-DD) or -1 if unparseable."""
    parts = str(value).strip().split("-")
    if len(parts) != 3:
        return -1
    try:
        import datetime as _dt

        return int(_dt.datetime(int(parts[0]), int(parts[1]), int(parts[2])).timestamp() / 86400)
    except Exception:
        return -1


def lookup_regulation(
    query: str | None = None,
    *,
    record_id: str | None = None,
    category: str | None = None,
    allow_stale: bool = False,
) -> dict[str, Any]:
    """Look up regulation records from the local verified database.

    - `record_id` loads one exact record.
    - `query` / `category` do a case-insensitive substring match over
      name/doc_id/region/category fields.

    Returns:
      {"records": [...], "verified": bool, "verification_required": [...],
       "lookup_failed": bool, "reason": str}

    Raises MBS-E201 (REGULATION_UNVERIFIABLE) when the requested record cannot
    be verified — e.g. a record is stale, or the caller asked for a category
    with no verified coverage. Callers surface REGULATORY_VERIFICATION_REQUIRED.
    """
    records: list[dict[str, Any]] = []
    if record_id:
        rec = _load_regulation(record_id)
        if rec is None:
            raise MbsError(
                MbsErrorCode.REGULATION_UNVERIFIABLE,
                f"Regulation record '{record_id}' is not present in the local verified database.",
                detail={"record_id": record_id, "action": "add a verified record first"},
            )
        records = [rec]
    else:
        # Scan the whole db directory.
        if not _REGULATORY_DB_DIR.is_dir():
            raise MbsError(
                MbsErrorCode.REGULATION_UNVERIFIABLE,
                "Regulatory database directory missing.",
                detail={"path": str(_REGULATORY_DB_DIR)},
            )
        for p in sorted(_REGULATORY_DB_DIR.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            text = " ".join(
                str(rec.get(k, "")) for k in ("name", "doc_id", "region", "category")
            ).lower()
            q = (query or "").lower()
            if query and q not in text:
                continue
            if category and str(rec.get("category", "")).lower() != category.lower():
                continue
            records.append(rec)

    if not records:
        raise MbsError(
            MbsErrorCode.REGULATION_UNVERIFIABLE,
            f"No regulation record matched query={query!r} category={category!r}.",
            detail={"query": query, "category": category},
        )

    today = _now_epoch_days()
    verification_required: list[str] = []
    for rec in records:
        # Freshness is judged by verified_on (when the record was verified),
        # NOT by issued_date (a regulation's issue date is naturally old).
        # A record without verified_on is conservatively treated as stale.
        verified_on = str(rec.get("verified_on") or "")
        if verified_on:
            ver = _parse_iso_date(verified_on)
            rec["stale"] = ver < 0 or (today - ver > MAX_REG_RECORD_AGE_DAYS)
        else:
            rec["stale"] = True
        verified = bool(rec.get("verified")) and not rec["stale"]
        rec["verified_now"] = verified
        if not verified:
            verification_required.append(rec.get("id", "?"))

    if verification_required and not allow_stale:
        raise MbsError(
            MbsErrorCode.REGULATION_UNVERIFIABLE,
            "One or more matched regulation records are unverified or stale; "
            "mark REGULATORY_VERIFICATION_REQUIRED and do not assert limit values.",
            detail={"verification_required": verification_required},
        )

    return {
        "records": records,
        "verified": len(verification_required) == 0,
        "verification_required": verification_required,
        "lookup_failed": False,
        "reason": None,
    }


def evaluate_against_limits(
    *,
    substance: str,
    concentration_mgL: float,
    matrix: str = "wastewater",
    limit_record_ids: list[str] | None = None,
    allow_stale: bool = False,
) -> dict[str, Any]:
    """Evaluate a measured concentration against verified regulatory limits.

    If no verified limit can be resolved for the substance/matrix, the result
    is `exceeded: "UNKNOWN"` and `verification_required: True` — the auditor
    refuses to assert compliance or non-compliance without a verified limit.
    """
    conc = float(concentration_mgL)
    limits_found: list[dict[str, Any]] = []
    verification_required: list[str] = []
    lookup: dict[str, Any] | None = None
    try:
        lookup = lookup_regulation(
            record_id=limit_record_ids[0] if limit_record_ids else None,
            query=f"{substance} {matrix}".strip() if not limit_record_ids else None,
            category=None,
            allow_stale=allow_stale,
        )
    except MbsError as exc:
        return {
            "substance": substance,
            "concentration_mgL": conc,
            "matrix": matrix,
            "exceeded": "UNKNOWN",
            "limits": [],
            "verification_required": [str(exc.detail.get("verification_required") or exc.detail.get("record_id") or "unknown")],
            "reason": exc.message,
        }

    if lookup:
        limits_found = [r for r in lookup["records"] if r.get("verified_now")]
        verification_required = lookup["verification_required"]

    if not limits_found:
        return {
            "substance": substance,
            "concentration_mgL": conc,
            "matrix": matrix,
            "exceeded": "UNKNOWN",
            "limits": [],
            "verification_required": verification_required or ["no-verified-limit"],
            "reason": "No verified regulatory limit available for this substance/matrix.",
        }

    # Resolve the limit value: prefer a flat `limit_mgL`, else look it up in
    # the record's `limits` map keyed by substance (+ optional matrix).
    limit_value = None
    first = limits_found[0]
    flat = first.get("limit_mgL")
    if flat is not None:
        limit_value = float(flat)
    else:
        limits_map = first.get("limits") or {}
        if substance in limits_map:
            limit_value = float(limits_map[substance])
        else:
            # Key may be compound, e.g. "nh4_n_mgL" — match by substance prefix.
            for key, val in limits_map.items():
                if key.startswith(substance):
                    limit_value = float(val)
                    break
    if limit_value is None:
        return {
            "substance": substance,
            "concentration_mgL": conc,
            "matrix": matrix,
            "exceeded": "UNKNOWN",
            "limits": limits_found,
            "verification_required": verification_required or ["no-limit-for-substance"],
            "reason": f"Verified record exists but carries no limit for substance '{substance}'.",
        }
    exceeded = conc > limit_value
    return {
        "substance": substance,
        "concentration_mgL": conc,
        "matrix": matrix,
        "exceeded": "YES" if exceeded else "NO",
        "limits": limits_found,
        "limit_mgL": limit_value,
        "margin": conc - limit_value,
        "verification_required": verification_required,
        "reason": None,
    }


def all_regulatory_context(categories: list[str] | None = None) -> dict[str, Any]:
    """Return the full verified regulatory context for the output envelope.

    Runs per-category lookups with allow_stale=True so the envelope can list
    what is verified and what is pending verification. Also returns a per-category
    verification map so the audit can gate on the categories RELEVANT to a site
    (a contained lab does not need discharge-limit verification; a field
    injection site does).

    CRITICAL: an empty database is NOT a verified state. If a category has no
    verified record, its `fully_verified` is False and `verification_required`
    carries the sentinel `no-verified-<category>-records`. The auditor never
    presents "no data" as "verified".
    """
    cats = categories or ["biosafety", "water", "groundwater", "soil", "waste",
                          "emissions", "laboratory", "emergency", "occupational"]
    records_by_cat: dict[str, list[dict[str, Any]]] = {}
    verification_required: list[str] = []
    for cat in cats:
        try:
            res = lookup_regulation(category=cat, allow_stale=True)
            records_by_cat[cat] = res["records"]
            verification_required.extend(res["verification_required"])
        except MbsError:
            records_by_cat[cat] = []
    # Category verification map. A category is fully verified ONLY when EVERY
    # record it carries is verified_now: one unverified limit-bearing record
    # (conflicting, stale, or missing verification date) leaves the whole
    # category a gap — the auditor never asserts a category is covered while an
    # applicable limit inside it is still REGULATORY_VERIFICATION_REQUIRED.
    categories_map: dict[str, dict[str, Any]] = {}
    for cat, recs in records_by_cat.items():
        verified_recs = [r for r in recs if r.get("verified_now")]
        all_verified = len(recs) > 0 and len(verified_recs) == len(recs)
        categories_map[cat] = {
            "records": len(recs),
            "verified_records": len(verified_recs),
            "fully_verified": all_verified,
        }
        if not all_verified:
            verification_required.append(f"category-{cat}-not-fully-verified")

    records: list[dict[str, Any]] = []
    for recs in records_by_cat.values():
        records.extend(recs)
    verification_required = sorted(set(verification_required))
    return {
        "regulations": records,
        "verification_required": verification_required,
        "fully_verified": len(records) > 0 and len(verification_required) == 0,
        "categories": categories_map,
    }


def required_categories_for_site(site: dict[str, Any]) -> list[str]:
    """Regulatory categories that MUST be verified for the site profile.

    Every site needs biosafety/laboratory/waste verification (strain handling,
    lab practice, waste handling). Sites that discharge to the environment,
    inject into groundwater, or expose personnel additionally require the
    relevant water/groundwater/emissions/occupational categories.

    IMPORTANT: the inference must not depend only on optional boolean flags —
    a plan that declares discharge (plan.waste.discharge_to_environment) or
    field-scale injection (release_type in request/plan semantics) must be
    treated as releasing even when the site flags are absent. Never let an
    absent optional flag downgrade a physically-releasing plan to 'contained'.
    """
    required = ["biosafety", "laboratory", "waste"]
    release = str(site.get("release_type") or "contained").lower()
    # Non-optional signals: plan.waste.discharge_to_environment, plan scale.
    plan = site.get("plan") or {}
    waste = plan.get("waste") or {}
    discharge_declared = bool(waste.get("discharge_to_environment"))
    if release in ("open_environment", "injection") or discharge_declared:
        required += ["water", "emissions"]
    if site.get("groundwater_injection") or discharge_declared or release == "injection":
        required += ["groundwater"]
    if site.get("confined_space") or site.get("personnel_exposure"):
        required += ["occupational"]
    return list(dict.fromkeys(required))


def regulatory_gaps_for_site(site: dict[str, Any], reg_context: dict[str, Any]) -> list[str]:
    """Categories required by the site that have no verified record.

    Returns empty when every site-relevant category has verified coverage.
    """
    categories_map = reg_context.get("categories") or {}
    gaps: list[str] = []
    for cat in required_categories_for_site(site):
        info = categories_map.get(cat) or {"fully_verified": False}
        if not info.get("fully_verified"):
            gaps.append(cat)
    return gaps
