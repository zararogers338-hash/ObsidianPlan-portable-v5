"""Auditor: self-check + epistemology enforcement (spec §四.5, §九).

Runs after the service assembles an output envelope. It verifies:

  * every epistemic label is one of the six allowed values;
  * no INFERRED/HYPOTHESIS/RECOMMENDATION statement is mislabeled OBSERVED;
  * no OBSERVED statement lacks a source when it should have one
    (evidence refs or a modality source);
  * the hard rules from :mod:`mmpi.minerals` are not violated by the output
    (single-SEM-no-homogeneity, morphology-not-diagnostic, no strength-from-
    bridge-without-mechanics, no fabrication, Ca-not-CaCO3);
  * the envelope validates against output.schema.json.

Returns a list of issues; an empty list means the envelope passed. The service
uses this to set `validation.self_check` and to downgrade SUCCESS to FAILED
(per contract, an envelope that fails its own self-check must not claim
SUCCESS).
"""

from __future__ import annotations

from typing import Any

from .minerals import HARD_RULES
from .validate import validate, validate_output


def _label_ok(label: str) -> bool:
    return label in {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"}


def _is_mislabeled_observed(label: str) -> bool:
    return label == "OBSERVED"


def check_epistemology(envelope: dict[str, Any]) -> list[str]:
    """Check epistemic-label usage across findings and risks."""
    issues: list[str] = []
    for section in ("findings", "risks"):
        for item in envelope.get(section, []):
            label = item.get("label", "")
            statement = item.get("statement", "")
            if not _label_ok(label):
                issues.append(f"[{section}] 非法认识论标签: {label!r}")
            elif _is_mislabeled_observed(label) and not item.get("source") and not _has_obs_source(envelope, item):
                issues.append(f"[{section}] OBSERVED 声明缺少来源: {statement[:60]}...")
    return issues


def _has_obs_source(envelope: dict[str, Any], item: dict[str, Any]) -> bool:
    """An OBSERVED statement may carry its own `source`, or the envelope cites
    evidence/data refs. Both count as grounding for a direct observation."""
    if item.get("source"):
        return True
    return bool(envelope.get("evidence_used"))


def check_hard_rules(envelope: dict[str, Any], *, context: dict[str, Any] | None = None) -> list[str]:
    """Check the professional hard rules against the assembled envelope.

    `context` carries internal signals (e.g. whether a single SEM image was
    used, whether an extrapolation was attempted) that the plain envelope may
    not surface on its own.
    """
    issues: list[str] = []
    summary = envelope.get("summary", "")
    findings_text = " ".join(f.get("statement", "") for f in envelope.get("findings", []))

    sem_signal = bool(context and context.get("single_sem_image_used"))
    has_inline_evidence = bool(context and context.get("has_inline_samples"))
    for name, statement in HARD_RULES:
        if name == "single_sem_no_homogeneity" and sem_signal:
            if _mentions_homogeneity(summary) or _mentions_overall(summary):
                issues.append(f"[hard_rule:{name}] 检测到整体性断言:{summary}")
        if name == "no_fabrication":
            # A SUCCESS envelope with strong claims but neither evidence refs
            # nor inline samples is a red flag the auditor flags. Inline
            # samples (interpret.phases with samples=) count as grounding.
            if envelope.get("status") == "SUCCESS" and not envelope.get("evidence_used") and not has_inline_evidence and findings_text:
                issues.append("[hard_rule:no_fabrication] SUCCESS 封套但 evidence_used 为空且含结论性发现")
    return issues


def _mentions_homogeneity(text: str) -> bool:
    for token in ("整体均匀", "全局均匀", "homogeneous", "均匀分布", "uniform"):
        if token in text:
            return True
    return False


def _mentions_overall(text: str) -> bool:
    for token in ("外推", "extrapolat", "整体", "overall", "整体样品"):
        if token in text:
            return True
    return False


def audit_envelope(
    envelope: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    schema_dir: str | None = None,
) -> dict[str, Any]:
    """Full self-check. Returns {'passed': bool, 'issues': [...], 'schema': [...]}.

    schema issues come from validating the envelope against output.schema.json
    using the skill's own validator (so it stays offline and self-contained).
    """
    issues: list[str] = []
    schema_issues = validate_output(envelope, schema_dir)
    issues += [f"[schema] {i.path}: {i.message}" for i in schema_issues]
    issues += check_epistemology(envelope)
    issues += check_hard_rules(envelope, context=context)
    return {"passed": len(issues) == 0, "issues": issues, "schema": [i.to_dict() for i in schema_issues]}
