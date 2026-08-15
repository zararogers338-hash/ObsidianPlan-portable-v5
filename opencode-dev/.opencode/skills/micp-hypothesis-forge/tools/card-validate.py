"""Hypothesis Card / Card Set strict validator.

Input (one JSON on stdin):
  {
    "schema": "schemas/hypothesis-card.schema.json" | "schemas/card-set.schema.json",
    "document": { ... card or card set ... }
  }

Emits {valid, errors} plus a small compliance audit specific to hypothesis
cards: epistemic label legality, refutation condition presence, observable
variables present, time scale present, scope/conditions present. Offline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, as_dict, emit_ok, run_tool
from mhfx import jsonschema
from mhfx import models as M

TOOL = "card-validate"

ALLOWED_SCHEMAS = {
    "schemas/hypothesis-card.schema.json": "card",
    "schemas/card-set.schema.json": "card_set",
}


def _audit_card(card: dict) -> dict:
    checks = {
        "epistemic_label_legal": card.get("epistemic_label") in M.EPISTEMIC_LABELS,
        "refutation_present": bool((card.get("refutation") or "").strip()),
        "mechanism_chain_present": bool(M.normalize_chain(card.get("mechanism_chain"))),
        "observables_present": bool(
            isinstance(card.get("observables"), (list, str)) and card.get("observables")),
        "time_scale_present": bool((card.get("time_scale") or "").strip()),
        "scope_present": bool((card.get("scope") or "").strip()),
        "prediction_direction_present": card.get("prediction_direction") in ("increase", "decrease", "no_change", "non_monotonic", "null"),
    }
    findings = []
    if not checks["epistemic_label_legal"]:
        findings.append("epistemic_label must be one of "
                        "OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION")
    if not checks["refutation_present"]:
        findings.append("refutation condition is empty — hypothesis is not falsifiable (MHX-E106)")
    if not checks["mechanism_chain_present"]:
        findings.append("mechanism_chain is empty or has fewer than 2 steps")
    if not checks["observables_present"]:
        findings.append("no observable variables declared")
    if not checks["time_scale_present"]:
        findings.append("time_scale is missing")
    if not checks["scope_present"]:
        findings.append("scope/conditions of applicability are missing")
    if not checks["prediction_direction_present"]:
        findings.append("prediction_direction missing or illegal "
                        "(increase/decrease/no_change/non_monotonic/null)")
    return {"checks": checks, "findings": findings,
            "audit_pass": not findings}


def main(payload: Any) -> dict:
    payload = as_dict(payload)
    schema = payload.get("schema")
    if schema not in ALLOWED_SCHEMAS:
        raise ToolError(
            "MHX-E105",
            f"schema must be one of {sorted(ALLOWED_SCHEMAS)}, got {schema!r}.",
            exit_code=2,
        )
    document = payload.get("document")
    if document is None:
        raise ToolError("MHX-E102", "missing required field `document`.", exit_code=2)

    errors = jsonschema.validate_document(document, schema)
    kind = ALLOWED_SCHEMAS[schema]

    audit: list[dict] = []
    if kind == "card":
        if isinstance(document, dict):
            audit.append(_audit_card(document))
    else:  # card set
        cards = document.get("cards") if isinstance(document, dict) else None
        if isinstance(cards, list):
            for c in cards:
                if isinstance(c, dict):
                    audit.append({**_audit_card(c), "id": c.get("id", "?")})

    return {
        "valid": not errors,
        "schema_errors": errors,
        "audit": audit,
        "audit_pass": bool(audit) and all(a["audit_pass"] for a in audit),
        "valid_and_audited": (not errors) and bool(audit) and all(a["audit_pass"] for a in audit),
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
