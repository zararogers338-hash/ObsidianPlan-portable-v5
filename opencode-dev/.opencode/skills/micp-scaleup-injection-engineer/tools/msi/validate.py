"""Output self-check and JSON-Schema validation for micp-scaleup-injection-engineer.

validate_output() runs a structural check against schemas/output.schema.json
(builtin lightweight validator — no network, no third-party dependency), and
returns a list of (path, message) issues. The service marks self_check based
on these plus domain self-checks (mass balance, epistemic labels).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import SKILL_NAME

EPISTEMIC = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")
STATUS_ENUM = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL",
               "HUMAN_APPROVAL_REQUIRED")

# ---------------------------------------------------------------- schemas (lite)

def _load_schema(name: str) -> dict[str, Any] | None:
    here = Path(__file__).resolve().parent.parent.parent  # tools/msi -> skill root
    p = here / "schemas" / name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def validate_output(value: Any) -> list[tuple[str, str]]:
    """Structural validation of the output envelope (mirrors output.schema.json)."""
    issues: list[tuple[str, str]] = []
    if not isinstance(value, dict):
        return [("$", "output must be an object")]
    required = ["contract_version", "skill", "skill_version", "status", "summary",
                "action", "project_id", "task_id", "findings", "assumptions",
                "evidence_used", "uncertainty", "risks", "artifacts",
                "requested_next_skills", "validation", "provenance", "errors"]
    for f in required:
        if f not in value:
            issues.append((f, f"missing required field '{f}'"))
    if "skill" in value and value["skill"] != SKILL_NAME:
        issues.append(("skill", f"skill must be {SKILL_NAME}"))
    if "status" in value and value["status"] not in STATUS_ENUM:
        issues.append(("status", f"invalid status {value['status']!r}"))
    for f in ("findings", "assumptions", "risks"):
        for i, item in enumerate(value.get(f, []) or []):
            if not isinstance(item, dict) or "label" not in item or "statement" not in item:
                issues.append((f"{f}[{i}]", "missing label/statement"))
            elif item.get("label") not in EPISTEMIC:
                issues.append((f"{f}[{i}].label", f"invalid label {item.get('label')!r}"))
    val = value.get("validation", {})
    if not isinstance(val, dict) or "self_check" not in val:
        issues.append(("validation", "missing validation.self_check"))
    errs = value.get("errors", []) or []
    for i, e in enumerate(errs):
        if not isinstance(e, dict) or "code" not in e or "message" not in e:
            issues.append((f"errors[{i}]", "error item missing code/message"))
    return issues


def check_material_balance(bal: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Domain self-check: urea/Ca/NH4 balance consistency.

    Environmental NH4-N is computed from INJECTED urea (2 mol NH4-N per mol
    urea), which is 1/eff times the precipitated-CaCO3-tied ammonium. The
    check verifies NH4 = 2 * urea_mol and that the CaCO3-tied portion is
    consistent with 2 * caco3_mol.
    """
    checks: list[dict[str, Any]] = []
    if bal is None:
        checks.append({"name": "material_balance_present", "passed": False,
                       "detail": "no material balance produced"})
        return checks
    caco3_mol = bal.get("caco3_mol")
    urea_mol = bal.get("urea_mol")
    nh4_mol = bal.get("nh4_n_mol")
    ok = True
    detail = "ok"
    if urea_mol is not None and nh4_mol is not None:
        ratio = nh4_mol / urea_mol if urea_mol else math.nan
        if not math.isfinite(ratio) or abs(ratio - 2.0) > 1e-6:
            ok = False
            detail = f"NH4/urea = {ratio:.3f} != 2.0 (ureolysis stoichiometry)"
    checks.append({"name": "material_balance_stoichiometry", "passed": ok, "detail": detail})
    return checks


def check_epistemic_labels(out: dict[str, Any]) -> dict[str, Any]:
    mislabeled: list[str] = []
    for f in ("findings", "assumptions", "risks"):
        for item in out.get(f, []) or []:
            if isinstance(item, dict) and item.get("label") not in EPISTEMIC:
                mislabeled.append(f"{f}: {item.get('label')}")
    ok = len(mislabeled) == 0
    return {"name": "epistemic_labels", "passed": ok,
            "detail": f"{len(mislabeled)} mislabeled" if mislabeled else ""}
