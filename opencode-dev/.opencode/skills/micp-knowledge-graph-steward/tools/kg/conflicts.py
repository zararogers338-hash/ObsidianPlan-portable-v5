"""Conflict detection and evidence tracing (spec §四.5, §五.4, §九.2).

Pure functions over a Projection. No writes, no network.

Conflict model:
  - A conflict exists between two claims that are COMPARABLE:
      * IDENTITY claims: two different entities both claim SAME_AS the same
        target (or each other) with no reconciling preference.
      * VALUE claims: same subject + same predicate, both carrying a numeric
        quantity whose units are compatible, and the relative difference
        exceeds the tolerance (default 20%).
      * CAUSAL claims: same subject + predicate with contradictory direction
        or contradictory polarity (e.g. increases vs decreases).
  - Conflicts are never silently resolved. They are recorded as OPEN with a
    reason; resolution requires an explicit resolution event with a preferred
    claim and a rationale (approval-gated at the service layer).

Evidence tracing (spec §九.2: every knowledge item has a source, a time, a
version, and an epistemic label; graph queries must return the evidence chain):
  - Each claim carries evidence_refs. `evidence_chain` returns, for a claim id,
    the claim plus every registered evidence record it references, with tier,
    sha256, retraction state, and source — so a query can show exactly why a
    claim is believed at its stated level.
"""

from __future__ import annotations

import math
from typing import Any

from .normalize import check_quantity, check_value_range, units_compatible
from .errors import KgeError, KgeErrorCode

DEFAULT_VALUE_TOLERANCE = 0.20  # relative difference beyond this is a conflict


def _value_relative_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return 0.0 if a == b else float("inf")
    return abs(a - b) / denom


def comparable(claim_a: dict[str, Any], claim_b: dict[str, Any]) -> bool:
    """Whether two claims can conflict at all."""
    if claim_a.get("_status") == "RETRACTED" or claim_b.get("_status") == "RETRACTED":
        return False
    if claim_a.get("claim_kind") != claim_b.get("claim_kind"):
        return False
    if claim_a.get("subject") != claim_b.get("subject"):
        return False
    if claim_a.get("predicate") != claim_b.get("predicate"):
        return False
    return True


def _identity_conflict(claim_a: dict[str, Any], claim_b: dict[str, Any]) -> str | None:
    """Two IDENTITY claims conflict when they map the same alias to different
    canonical entities."""
    target_a = claim_a.get("object") or claim_a.get("target_entity")
    target_b = claim_b.get("object") or claim_b.get("target_entity")
    if target_a and target_b and target_a != target_b:
        return (f"identity conflict: alias resolves to different entities "
                f"{target_a!r} vs {target_b!r}")
    return None


def _value_conflict(claim_a: dict[str, Any], claim_b: dict[str, Any],
                    tolerance: float) -> str | None:
    """VALUE claims conflict when quantities are unit-compatible and differ
    beyond tolerance; incompatible units are an error state (KGE-E203)."""
    qa = claim_a.get("quantity")
    qb = claim_b.get("quantity")
    if not (qa and qb):
        return None  # not both numeric; not comparable
    va, ua = qa.get("value"), qa.get("unit")
    vb, ub = qb.get("value"), qb.get("unit")
    if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
        return None
    if isinstance(va, bool) or isinstance(vb, bool):
        return None
    if not units_compatible(ua, ub):
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"Claims compare incompatible units: {ua!r} vs {ub!r}.",
                       detail={"claim_a": claim_a.get("id"), "claim_b": claim_b.get("id"),
                               "unit_a": ua, "unit_b": ub})
    diff = _value_relative_diff(va, vb)
    if diff > tolerance:
        return (f"value conflict: {claim_a['id']}={va} {ua} vs "
                f"{claim_b['id']}={vb} {ub} (rel. diff {diff:.1%} > {tolerance:.0%})")
    return None


def _causal_conflict(claim_a: dict[str, Any], claim_b: dict[str, Any]) -> str | None:
    """CAUSAL claims conflict on opposing polarity for the same pair."""
    sa, sb = claim_a.get("polarity"), claim_b.get("polarity")
    if not sa or not sb:
        return None
    opposing = {"increases": "decreases", "decreases": "increases"}
    if opposing.get(sa) == sb or opposing.get(sb) == sa:
        return (f"causal conflict: same pair claimed {sa} vs {sb}.")
    return None


def _categorical_conflict(claim_a: dict[str, Any], claim_b: dict[str, Any]) -> str | None:
    """TYPE / OBSERVATION / SYNONYM / NORMATIVE claims with the same subject and
    predicate but different categorical objects (e.g. mineral phase claimed as
    'calcite' by one source and 'vaterite' by another). Both statements coexist
    in the graph; the contradiction is surfaced as an open conflict, never
    resolved by overwriting the older claim."""
    obj_a = claim_a.get("object")
    obj_b = claim_b.get("object")
    if obj_a and obj_b and obj_a != obj_b:
        return f"categorical conflict: '{obj_a}' vs '{obj_b}' for the same subject+predicate"
    return None


def detect_conflicts(proj: Any, *, tolerance: float = DEFAULT_VALUE_TOLERANCE,
                     only_new: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Scan all claim pairs and return conflict descriptors.

    `only_new` (a single claim dict) restricts the scan to pairs involving
    that claim; used by ingestion to avoid O(n^2) rescans. When omitted, the
    whole graph is scanned (used by `graph.conflict_scan`).
    """
    claims = proj.claims
    if only_new is not None:
        claims = [only_new]
    conflicts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _compare(a: dict[str, Any], b: dict[str, Any]) -> None:
        key = tuple(sorted((a["id"], b["id"])))
        if key in seen:
            return
        seen.add(key)
        if not comparable(a, b):
            return
        reason: str | None = None
        kind = a.get("claim_kind")
        if kind == "VALUE":
            reason = _value_conflict(a, b, tolerance)
        elif kind == "CAUSAL":
            reason = _causal_conflict(a, b)
        elif kind == "IDENTITY":
            reason = _identity_conflict(a, b)
        else:
            # TYPE / OBSERVATION / SYNONYM / NORMATIVE: same subject+predicate
            # with different categorical objects is a contradiction (e.g. a
            # sample claimed to be calcite AND aragonite). Both facts coexist;
            # the conflict is recorded, never silently resolved.
            reason = _categorical_conflict(a, b)
        if reason:
            conflicts.append({
                "claim_a": a["id"], "claim_b": b["id"],
                "kind": "claim", "reason": reason,
                "claim_kind": kind,
            })

    for i, a in enumerate(claims):
        for b in proj.claims:
            if a["id"] == b["id"]:
                continue
            _compare(a, b)
    return conflicts


def is_open_conflict(proj: Any, claim_a: str, claim_b: str) -> bool:
    for c in proj.conflicts:
        if c["status"] == "OPEN" and {c["claim_a"], c["claim_b"]} == {claim_a, claim_b}:
            return True
    return False


def evidence_chain(proj: Any, claim_id: str) -> dict[str, Any]:
    """Return the evidence trail behind a claim (acceptance §九.2).

    The result lists every referenced evidence record with tier, source,
    sha256, retraction state, plus the claim's own epistemic label and
    confidence. Missing refs are surfaced as unresolved — never fabricated.
    """
    claim = proj.claim_by_id(claim_id)
    if claim is None:
        raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                       f"Unknown claim id '{claim_id}'.",
                       detail={"how_to_fix": "Use graph.get_claim or list claims via graph.list."})
    refs = claim.get("evidence_refs", [])
    chain: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for ref in refs:
        rec = next((e for e in proj.evidence if e["ref"] == ref), None)
        if rec is None:
            unresolved.append(ref)
            continue
        chain.append({
            "ref": ref,
            "tier": rec.get("tier"),
            "source": rec.get("source"),
            "summary": rec.get("summary"),
            "sha256": rec.get("sha256"),
            "retracted": rec.get("retracted", False),
            "recorded_revision": rec.get("recorded_revision"),
        })
    return {
        "claim_id": claim_id,
        "epistemic_label": claim.get("epistemic_label"),
        "confidence": claim.get("confidence"),
        "evidence_chain": chain,
        "unresolved_refs": unresolved,
    }


def normalize_claim_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Preflight a claim draft: resolve units and ranges.

    Raises KGE-E203 on unit/range problems so ingestion fails loudly instead
    of storing garbage. Returns a copy (no mutation of the caller's dict).
    """
    claim = dict(draft)
    quantity = claim.get("quantity")
    if quantity:
        claim["quantity"] = check_quantity(quantity)
    domain = claim.get("domain_range")
    if domain:
        lo, hi, unit = domain[0], domain[1], domain[2]
        if claim.get("quantity"):
            check_value_range(claim["quantity"]["value"], claim["quantity"].get("unit") or unit,
                              low=lo, high=hi, label=claim.get("id", "value"))
    return claim
