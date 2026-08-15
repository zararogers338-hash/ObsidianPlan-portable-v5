"""Evidence source-chain checker (Evidence 来源链检查器).

Audits the chain from claim → citation → primary source:

  - every claim cites at least one resolvable evidence ref (chain has a head)
  - every ref used by a claim is present in the supplied evidence set
  - every evidence item carries a locator/DOI resolvable by some protocol
  - chain transitivity: a claim that rests on a review must reach a primary
    source, or the reliance-on-review-only is flagged
  - fabricated/unresolvable locators are flagged as chain breaks

Offline, deterministic, pure stdlib.
"""

from __future__ import annotations

import re
from typing import Any

from common import ToolError, emit_progress
from citation import _extract_doi, _looks_like_fabricated_locator
from errors import OrtErrorCode, OrtError


def _check_chain(payload: dict[str, Any]) -> dict[str, Any]:
    targets = payload.get("targets") or []
    refs = {str(r.get("ref_id")): r for r in (payload.get("evidence_refs") or []) if r.get("ref_id")}
    missing_in_chain: list[dict] = []
    unreachable_claims: list[dict] = []
    broken_locators: list[dict] = []
    review_only: list[dict] = []

    for t in targets:
        t_id = str(t.get("id", "?"))
        cites = t.get("cites") or []
        if not cites:
            missing_in_chain.append({
                "target_id": t_id,
                "issue": "claim cites no evidence reference at all",
                "severity": "MAJOR",
            })
            continue
        for cr in cites:
            cr = str(cr)
            if cr not in refs:
                unreachable_claims.append({
                    "target_id": t_id,
                    "missing_ref": cr,
                    "issue": "cited ref is not present in the evidence set",
                    "severity": "CRITICAL",
                })
                continue
            ref = refs[cr]
            locator = str(ref.get("locator", "")).strip()
            if _looks_like_fabricated_locator(locator):
                broken_locators.append({
                    "target_id": t_id,
                    "ref_id": cr,
                    "locator": locator,
                    "issue": "locator is not resolvable by any protocol; fabrication candidate",
                    "severity": "BLOCKING",
                })
            elif not locator:
                broken_locators.append({
                    "target_id": t_id,
                    "ref_id": cr,
                    "locator": "",
                    "issue": "evidence ref has no locator",
                    "severity": "CRITICAL",
                })
            # reliance on review only: ref claims to be a review but the claim
            # is load-bearing → the chain must also reach a primary source.
            media = str(ref.get("media_type", "")).lower()
            is_review = "review" in media or "综述" in str(ref.get("note", ""))
            if is_review and t.get("type") in ("conclusion", "claim"):
                review_only.append({
                    "target_id": t_id,
                    "ref_id": cr,
                    "issue": "load-bearing claim rests on a review; primary source unreached",
                    "severity": "MINOR",
                })

    return {
        "summary": {
            "targets": len(targets),
            "refs": len(refs),
            "claims_without_citations": len(missing_in_chain),
            "unreachable_citations": len(unreachable_claims),
            "broken_locators": len(broken_locators),
            "review_only_load_bearing": len(review_only),
        },
        "findings": missing_in_chain + unreachable_claims + broken_locators + review_only,
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("provenance: checking evidence source chains")
    required = ["targets"]
    from common import validate_required
    missing = validate_required(payload, required)["missing"]
    if missing:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "provenance: missing required fields",
                       detail={"missing": missing})
    if not payload.get("evidence_refs"):
        raise OrtError(OrtErrorCode.EVIDENCE_CHAIN_BROKEN,
                       "provenance: evidence_refs empty; a chain with no sources is broken",
                       detail={"how_to_fix": "supply the evidence references each claim cites"})
    return _check_chain(payload)


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("provenance", lambda: main(read_stdin_envelope()))
