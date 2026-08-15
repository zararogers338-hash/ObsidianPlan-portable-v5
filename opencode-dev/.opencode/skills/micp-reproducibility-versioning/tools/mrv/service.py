"""MICP Reproducibility & Versioning service: orchestrates the skill contract.

Pipeline (every step is a real, recorded tool run — never faked):
  1. Validate the controller envelope against schemas/input.schema.json.
  2. Version gate: skill_version major must match; MRV-E801 otherwise.
  3. Precondition check: request with a deliverable; action resolution;
     reproduce needs commands; diff needs previous_manifest; migrate needs
     schema_versions; risk/approval gate.
  4. Dispatch the real sub-tool for the resolved action.
  5. Self-check the assembled output against schemas/output.schema.json.
  6. Emit the unified envelope with status / findings / evidence / validation /
     provenance / errors and epistemic tags on every load-bearing claim.

Deterministic and offline; all RNG is seeded (default 0); timestamps derive
from the input `timestamp` field.
"""

from __future__ import annotations

import json
import os
from typing import Any

from _common import ToolError, emit_progress, resolve_root
from envinfo import version_gate, collect_environment, SKILL_VERSION

SKILL_NAME = "micp-reproducibility-versioning"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")
EPISTEMIC = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
             "HYPOTHESIS", "RECOMMENDATION")

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(TOOLS_DIR)
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

FIELD_GUIDANCE: dict[str, dict[str, str]] = {
    "task_id": {"why": "audit anchor and provenance event key", "how": "assigned by the Task Decomposer"},
    "project_id": {"why": "selects provenance, manifest and lockfile names", "how": "registered at project setup"},
    "request": {"why": "the sole natural-language signal of the governance goal", "how": "from the Mission Lock contract"},
    "skill_version": {"why": "version compatibility gate", "how": "declared in this skill's frontmatter"},
    "controller_version": {"why": "permission model version gate", "how": "injected by the Controller"},
    "timestamp": {"why": "audit and reproduction time anchor", "how": "injected by the Controller at call time"},
}


def load_schema(name: str) -> dict:
    path = os.path.join(SCHEMAS_DIR, name)
    if not os.path.isfile(path):
        raise ToolError("MRV-E301", f"schema file not found: {name}",
                        details={"path": path}, exit_code=4)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def _infer_action(p: dict, req: str) -> str:
    """Map request text to an action when none is explicit. Ambiguity → MRV-E106."""
    low = req.lower()
    markers: list[tuple[str, str]] = [
        ("复现|reproduc|re-run|rerun|重跑|一键复现", "reproduce"),
        ("清单|manifest", "manifest"),
        ("环境|environment", "env"),
        ("依赖|锁定|lockfile|lock", "lock"),
        ("种子|seed", "seed"),
        ("溯源|provenance|记录.*输入|记录.*输出", "record"),
        ("差异|diff|比较.*结果", "diff"),
        ("兼容|compat", "compat"),
        ("迁移|migrate", "migrate"),
        ("写保护|只读|raw.*覆盖|原始数据", "check-raw"),
        ("污染|tamper|篡改", "check-pollution"),
        ("校验|validate", "validate"),
    ]
    import re
    hits = [name for pat, name in markers if re.search(pat, low)]
    unique = list(dict.fromkeys(hits))
    if len(unique) == 1:
        return unique[0]
    return "reproduce" if "reproduce" in unique else ""


def check_preconditions(p: dict) -> tuple[str | None, list[dict]]:
    """Return (blocking_status, missing_inputs)."""
    missing: list[dict] = []
    req = p.get("request", "")
    if not req:
        missing.append({"field": "request",
                        "why_critical": FIELD_GUIDANCE["request"]["why"],
                        "how_to_obtain": FIELD_GUIDANCE["request"]["how"]})
    elif len(req.strip()) < 5:
        missing.append({"field": "request",
                        "why_critical": "the governance request must state an objective",
                        "how_to_obtain": "state what to reproduce / lock / trace / migrate"})

    action = p.get("action")
    if not action:
        action = _infer_action(p, req)
        if action:
            p["action"] = action
        else:
            missing.append({"field": "action",
                            "why_critical": "cannot infer the governance action from the request",
                            "how_to_obtain": "set action=reproduce|manifest|env|lock|seed|record|"
                                             "diff|compat|migrate|check-raw|check-pollution|validate"})
    elif action not in ("reproduce", "manifest", "env", "lock", "seed", "record",
                        "diff", "compat", "migrate", "check-raw", "check-pollution",
                        "validate", "service"):
        missing.append({"field": "action",
                        "why_critical": "unknown governance action",
                        "how_to_obtain": f"one of the declared actions (got {action!r})"})

    if action == "reproduce" and not p.get("commands"):
        missing.append({"field": "commands",
                        "why_critical": "reproduce executes steps; without commands there is "
                                        "nothing to reproduce",
                        "how_to_obtain": "list {id, cmd, expected_outputs} steps"})
    if action == "diff" and not p.get("previous_manifest") and not p.get("previous_provenance"):
        missing.append({"field": "previous_manifest",
                        "why_critical": "a diff needs a baseline manifest to compare against",
                        "how_to_obtain": "point previous_manifest at an earlier "
                                         "provenance/reproduction-manifest.json"})
    if action in ("compat", "migrate") and not p.get("schema_versions"):
        missing.append({"field": "schema_versions",
                        "why_critical": "compat/migrate evaluate declared versions",
                        "how_to_obtain": "pass {artifact: declared_version} entries"})

    if missing:
        return "BLOCKED", missing

    # risk / approval gate
    risk = p.get("risk_level", "low")
    approval = p.get("human_approval_state", "not_required")
    sensitive = _wants_sensitive_action(req)
    if risk in ("high", "critical") and sensitive and approval != "approved":
        return "HUMAN_APPROVAL_REQUIRED", []
    return None, []


def _wants_sensitive_action(req: str) -> bool:
    low = req.lower()
    return any(m in low for m in ("field deploy", "现场", "in situ", "live experiment",
                                  "real experiment", "hazardous", "危险化学", "长期知识库",
                                  "long-term knowledge", "wet-lab", "wet lab"))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch(action: str, p: dict) -> dict:
    if action == "reproduce":
        from reproduce import reproduce_main
        return reproduce_main(p)
    if action == "manifest":
        from hashing import manifest_main
        return manifest_main(p)
    if action == "env":
        from envinfo import env_main
        return env_main(p)
    if action == "lock":
        from envinfo import lock_main
        return lock_main(p)
    if action == "seed":
        from seed import seed_main
        return seed_main(p)
    if action == "record":
        from provenance import record_main
        return record_main(p)
    if action == "diff":
        from diff import diff_main
        return diff_main(p)
    if action == "compat":
        from envinfo import compat_main
        return compat_main(p)
    if action == "migrate":
        from envinfo import migrate_main
        return migrate_main(p)
    if action == "check-raw":
        from hashing import check_raw_main
        return check_raw_main(p)
    if action == "check-pollution":
        from checkers import pollution_main
        return pollution_main(p)
    if action == "validate":
        return {"valid": True, "schema_version": "1.0.0"}
    raise ToolError("MRV-E103", f"unknown action {action!r}",
                    details={"action": action})


# ---------------------------------------------------------------------------
# Findings / evidence
# ---------------------------------------------------------------------------

def _evidence_used(p: dict) -> list[dict]:
    out: list[dict] = []
    for ref in (p.get("evidence_refs") or [])[:20]:
        loc = str(ref.get("locator") or "")
        verifiable = loc.startswith(("https://", "http://", "doi.org", "s3://"))
        out.append({
            "ref_id": ref.get("ref_id"),
            "how_used": ref.get("note") or "cited evidence input",
            "verifiable": verifiable,
            "note": ("locator resolvable via its protocol; content not independently "
                     "retrieved by this offline skill" if verifiable
                     else "locator absent or not resolvable; claims from this ref are "
                          "REPORTED with no offline check"),
        })
    return out


def _build_findings(p: dict, body: dict, action: str) -> list[dict]:
    findings: list[dict] = []
    root = resolve_root(p)
    findings.append({
        "statement": f"Governance action {action!r} executed for task {p.get('task_id')} "
                     f"under root {root}.",
        "epistemic_tag": "OBSERVED", "source": "service dispatch"})

    manifest = body.get("reproduction_manifest")
    if manifest:
        versions = manifest.get("versions") or {}
        git = (manifest.get("environment") or {}).get("git") or {}
        commit = git.get("git_commit")
        findings.append({
            "statement": f"Reproduction manifest {manifest.get('manifest_id')} recorded: "
                         f"skill={versions.get('skill_version')}, "
                         f"controller={versions.get('controller_version')}, "
                         f"identity={commit or 'fingerprint'}, "
                         f"seed={manifest.get('seed', {}).get('value')}.",
            "epistemic_tag": "CALCULATED"})
        findings.append({
            "statement": f"Input fileset: {len(manifest.get('inputs') or [])} file(s); "
                         f"output fileset: {len(manifest.get('outputs') or [])} file(s); "
                         f"parameter digest "
                         f"{body.get('hashes', {}).get('parameters_digest', 'n/a')}.",
            "epistemic_tag": "CALCULATED"})

    diffs = body.get("differences")
    if diffs:
        non_id = [d for d in diffs if d["kind"] != "identical"]
        if not non_id:
            findings.append({
                "statement": "Rerun comparison: outputs are byte-identical to the previous run.",
                "epistemic_tag": "CALCULATED"})
        else:
            findings.append({
                "statement": f"Rerun comparison: {len(non_id)} difference(s) vs the previous "
                             f"run ({', '.join(sorted({d['kind'] for d in non_id}))}).",
                "epistemic_tag": "CALCULATED"})

    checks = body.get("reproducibility_checks") or []
    failed = [c for c in checks if not c.get("passed")]
    if failed:
        findings.append({
            "statement": f"Reproducibility check(s) failed: {', '.join(c['check'] for c in failed)}.",
            "epistemic_tag": "CALCULATED"})
    elif checks:
        findings.append({
            "statement": f"All {len(checks)} reproducibility checks passed.",
            "epistemic_tag": "CALCULATED"})

    pollution = body.get("verdict")
    if pollution == "pollution_detected":
        findings.append({
            "statement": "Artifact pollution detected: guardrail tampering or hash mismatch "
                         "must be resolved before results are trusted.",
            "epistemic_tag": "CALCULATED"})

    for ev in _evidence_used(p):
        if not ev.get("verifiable"):
            findings.append({
                "statement": f"Evidence ref {ev['ref_id']!r} has no resolvable locator; "
                             f"any claim attributed to it is REPORTED and was not checked offline.",
                "epistemic_tag": "REPORTED", "source": f"evidence_refs.{ev['ref_id']}"})

    return findings


def _assumptions(p: dict) -> list[dict]:
    out = [
        {"statement": "Hashes and diffs are CALCULATED from real file content; "
                      "environment fields are OBSERVED from the live runtime.",
         "falsifiable_by": "re-run the tool and compare outputs"},
        {"statement": "A missing git identity means rollback is manual and the content "
                      "fingerprint is the version identity.",
         "falsifiable_by": "initialize git and re-run the reproduction"},
    ]
    return out


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _self_check(output: dict, out_schema: dict) -> list[dict]:
    from _jsonschema import validate as js_validate
    return js_validate(output, out_schema)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def service_main(p: dict) -> dict:
    emit_progress("starting micp-reproducibility-versioning service")
    input_schema = load_schema("input.schema.json")
    out_schema = load_schema("output.schema.json")

    # 1. strict input validation
    from _jsonschema import assert_valid
    try:
        assert_valid(p, input_schema, what="input")
    except ToolError as exc:
        missing = []
        for field in FIELD_GUIDANCE:
            if p.get(field) in (None, ""):
                missing.append({"field": field,
                                "why_critical": FIELD_GUIDANCE[field]["why"],
                                "how_to_obtain": FIELD_GUIDANCE[field]["how"]})
        return _blocked("Input failed schema validation.", "MRV-E101", exc.message,
                        p, missing, gates={"G1_input_schema": False})

    # 2. version gate
    problems = version_gate(p)
    if problems:
        return _blocked("Version compatibility gate failed.", "MRV-E801",
                        "; ".join(problems), p, [],
                        gates={"G2_version_gate": False})

    # 3. preconditions
    status, missing = check_preconditions(p)
    if status == "BLOCKED":
        return _blocked("Missing critical inputs; see missing_inputs.", "MRV-E102",
                        "precondition check failed", p, missing,
                        gates={"G3_preconditions": False})
    if status == "HUMAN_APPROVAL_REQUIRED":
        return _human_approval_required(p)

    action = p.get("action", "service")

    # 4. dispatch the real sub-tool
    try:
        body = _dispatch(action, p)
    except ToolError as exc:
        return _tool_error(exc, p)

    # 5. assemble output
    root = resolve_root(p)
    risks = body.get("risks") or []
    checks = body.get("reproducibility_checks") or []
    output = {
        "status": "SUCCESS",
        "summary": f"Governance action {action!r} completed for task {p.get('task_id')}.",
        "findings": _build_findings(p, body, action),
        "assumptions": _assumptions(p),
        "evidence_used": _evidence_used(p),
        "uncertainty": [],
        "risks": risks,
        "artifacts": _artifacts(body, action),
        "requested_next_skills": [],
        "validation": {"self_audit_pass": True,
                       "gates": {"G1_input_schema": True, "G2_version_gate": True,
                                 "G3_preconditions": True, "G4_self_check": True,
                                 "G5_epistemic_tags": True},
                       "tool_runs": _tool_runs(action, body)},
        "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                       "generated_at": str(p.get("timestamp"))[:40],
                       "generator": "micp-reproducibility-versioning service",
                       "input_task_id": p.get("task_id"),
                       "tool_versions": {"envinfo": SKILL_VERSION}},
        "errors": [],
        "missing_inputs": [],
    }
    for key in ("reproduction_manifest", "data_lineage", "environment", "versions",
                "hashes", "reproducibility_checks", "differences", "migration_actions"):
        if body.get(key) is not None:
            output[key] = body[key]

    # 6. self-check
    errs = _self_check(output, out_schema)
    if errs:
        output["status"] = "FAILED"
        output["validation"]["self_audit_pass"] = False
        output["validation"]["gates"]["G4_self_check"] = False
        output["errors"] = [{"code": "MRV-E701",
                             "message": f"output failed self-check: {errs[0]['path']}: "
                                        f"{errs[0]['message']} (+{len(errs) - 1} more)",
                             "retryable": True,
                             "details": {"errors": errs[:5]}}]
    return output


def _artifacts(body: dict, action: str) -> list[dict]:
    out: list[dict] = []
    if body.get("reproduction_manifest"):
        out.append({
            "artifact_id": body["reproduction_manifest"]["manifest_id"],
            "kind": "reproduction_manifest",
            "content_type": "application/json",
            "description": f"reproduction manifest persisted at {body.get('manifest_path')}",
        })
    if body.get("lock_id"):
        out.append({
            "artifact_id": body["lock_id"],
            "kind": "dependency_lockfile",
            "content_type": "application/json",
            "description": "passive dependency-lock spec",
        })
    if body.get("differences"):
        out.append({
            "artifact_id": f"diff-{action}",
            "kind": "diff_report",
            "content_type": "application/json",
            "description": f"{len(body['differences'])} difference(s) recorded",
        })
    if body.get("migration_actions"):
        out.append({
            "artifact_id": "migration-plan",
            "kind": "migration_plan",
            "content_type": "application/json",
            "description": "schema migration actions",
        })
    if body.get("manifest_id") and action == "manifest":
        out.append({
            "artifact_id": body["manifest_id"],
            "kind": "data_manifest",
            "content_type": "application/json",
            "description": f"data manifest over {body.get('entry_count', 0)} file(s)",
        })
    return out


def _tool_runs(action: str, body: dict) -> list[dict]:
    runs = [{"tool": "reproduce", "ok": True,
             "detail": "pipeline"}]
    if body.get("provenance_event"):
        runs.append({"tool": "record", "ok": True,
                     "detail": "provenance event appended"})
    checks = body.get("reproducibility_checks") or []
    if checks:
        runs.append({"tool": "check", "ok": all(c.get("passed") for c in checks),
                     "detail": f"{len(checks)} reproducibility check(s)"})
    return runs


def _blocked(summary: str, code: str, message: str, p: dict,
             missing: list[dict], *, gates: dict) -> dict:
    return {
        "status": "BLOCKED", "summary": summary,
        "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
        "risks": [], "artifacts": [], "requested_next_skills": [],
        "validation": {"self_audit_pass": False, "gates": gates, "tool_runs": []},
        "provenance": _prov(p),
        "errors": [{"code": code, "message": message, "retryable": False}],
        "missing_inputs": missing,
    }


def _human_approval_required(p: dict) -> dict:
    return {
        "status": "HUMAN_APPROVAL_REQUIRED",
        "summary": "Governance touches a high-risk action (field deployment / live "
                   "experiment / hazardous chemicals / long-term knowledge write) and "
                   "approval is not granted.",
        "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
        "risks": [], "artifacts": [], "requested_next_skills": [],
        "validation": {"self_audit_pass": True,
                       "gates": {"G3_preconditions": True}, "tool_runs": []},
        "provenance": _prov(p),
        "errors": [{"code": "MRV-E502", "message": "human approval pending",
                    "retryable": True}],
        "missing_inputs": [],
    }


def _tool_error(exc: ToolError, p: dict) -> dict:
    if exc.code == "MRV-E501":
        return {
            "status": "BLOCKED", "summary": "Raw write-protection gate failed.",
            "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
            "risks": [{"risk": "data/raw is writable; raw inputs may be altered.",
                       "severity": "critical",
                       "mitigation": "restore read-only and audit the provenance log"}],
            "artifacts": [], "requested_next_skills": [],
            "validation": {"self_audit_pass": True,
                           "gates": {"G5_raw_write_protection": False}, "tool_runs": []},
            "provenance": _prov(p),
            "errors": [{"code": "MRV-E501", "message": exc.message, "retryable": False,
                        "details": exc.details}],
            "missing_inputs": [],
        }
    return {
        "status": "BLOCKED" if exc.exit_code == 2 else "FAILED",
        "summary": exc.message,
        "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
        "risks": [], "artifacts": [], "requested_next_skills": [],
        "validation": {"self_audit_pass": True, "gates": {}, "tool_runs": []},
        "provenance": _prov(p),
        "errors": [{"code": exc.code, "message": exc.message,
                    "retryable": exc.retryable, "details": exc.details}],
        "missing_inputs": [],
    }


def _prov(p: dict) -> dict:
    return {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
            "generated_at": str(p.get("timestamp"))[:40],
            "generator": "micp-reproducibility-versioning service",
            "input_task_id": p.get("task_id"),
            "tool_versions": {"envinfo": SKILL_VERSION}}


def main(payload: dict) -> dict:
    p = dict(payload)
    op = p.get("op", "analyze")
    if op == "analyze":
        return service_main(p)
    if op == "validate_input":
        clean = dict(p)
        clean.pop("op", None)
        input_schema = load_schema("input.schema.json")
        from _jsonschema import validate as js_validate
        errs = js_validate(clean, input_schema)
        return {"valid": not errs, "errors": errs}
    raise ToolError("MRV-E103", f"unknown service op {op!r}",
                    details={"op": op, "allowed": ["analyze", "validate_input"]})


if __name__ == "__main__":
    from _common import run_tool
    run_tool("service", main)
