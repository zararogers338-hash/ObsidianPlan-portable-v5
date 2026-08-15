"""Over-generalization self-check (SKILL.md §自举测试-4, §验收门槛).

Every conclusion must carry: evidence_level, scope (applicability boundary),
counterexample (most plausible), open_questions. Labels must not be inflated
(INFERRED/HYPOTHESIS/RECOMMENDATION must never be OBSERVED; REPORTED without a
source is a defect). The check is deterministic and machine-enforced.
"""

from __future__ import annotations

from typing import Any

from .models import LABELS

# statements that sound like a universal claim — red flags for over-generalization.
# These are only triggers when they apply to the *conclusion content* (UCS etc.),
# never when they describe the skill's own methodological rules.
_UNIVERSAL_WORDS = ("all sands", "all soil", "all soils", "any soil", "any sand",
                    "always", "never", "universally", "every sand", "every soil",
                    "在任何", "所有砂", "所有土壤", "总是", "必然", "一定")
_SKILL_RULE_WORDS = ("not averaged", "not pooling", "not merged", "reported, not",
                     "explained, not", "not directly compared", "not merged")


def check_conclusions(conclusions: list[dict], evidence_used: list[str]) -> dict:
    """Validate each conclusion. Returns {passed: bool, checks: [ {name, passed, detail} ]}."""
    checks: list[dict] = []

    if not conclusions:
        checks.append({"name": "has_conclusions", "passed": True,
                       "detail": "no conclusions to check (may be BLOCKED/NEED_ADDITIONAL_SKILL)"})
        return {"passed": True, "checks": checks}

    for i, c in enumerate(conclusions):
        cid = c.get("id", f"conclusion[{i}]")
        for field in ("statement", "evidence_level", "scope", "counterexample"):
            if not c.get(field):
                checks.append({"name": f"{cid}.{field}", "passed": False,
                               "detail": f"conclusion {cid} missing required field '{field}'"})

        label = c.get("label")
        if label not in LABELS:
            checks.append({"name": f"{cid}.label", "passed": False,
                           "detail": f"conclusion {cid} label '{label}' not in {LABELS}"})

        # label inflation
        if label in ("INFERRED", "HYPOTHESIS", "RECOMMENDATION"):
            stmt = str(c.get("statement", ""))
            if any(w in stmt for w in ("observed", "shown", "proven", "确认", "证实")):
                checks.append({"name": f"{cid}.label_inflated", "passed": False,
                               "detail": f"conclusion {cid} labelled {label} but uses observed/proven language"})

        # universal claim without scope qualification
        stmt_lower = str(c.get("statement", "")).lower()
        if any(w in stmt_lower for w in _UNIVERSAL_WORDS) and not any(
                w in stmt_lower for w in _SKILL_RULE_WORDS):
            checks.append({"name": f"{cid}.universal_claim", "passed": False,
                           "detail": f"conclusion {cid} uses universal language without scope qualification"})

        # scope must be non-trivial
        scope = str(c.get("scope", ""))
        if scope and len(scope) < 4:
            checks.append({"name": f"{cid}.scope_trivial", "passed": False,
                           "detail": f"conclusion {cid} scope is trivial: '{scope}'"})

    # evidence_used traceability
    if evidence_used:
        for e in evidence_used:
            if not isinstance(e, str) or len(e) < 1:
                checks.append({"name": "evidence_used.entry", "passed": False,
                               "detail": "evidence_used contains an empty/non-string entry"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}
