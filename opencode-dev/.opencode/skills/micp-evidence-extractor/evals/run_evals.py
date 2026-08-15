#!/usr/bin/env python3
"""Offline deterministic eval runner for micp-evidence-extractor.

Parses `evals/cases.yaml`, runs each case through the real CLI, and reports
the seven minimum performance indicators from skill.yaml:

  structured_output_pass_rate, tool_invocation_rate,
  evidence_traceability_rate, missing_input_detection_rate,
  adversarial_interception_rate, repeat_run_consistency,
  mean_failure_recovery_time.

Pure stdlib. Needs no network. Exit code 0 when all hard thresholds pass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Any

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(SKILL_ROOT, "tools", "mee")
CLI = os.path.join(TOOLS_DIR, "cli.py")
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

THRESHOLDS = {
    "structured_output_pass_rate": 0.95,
    "tool_invocation_rate": 1.0,
    "evidence_traceability_rate": 0.9,
    "missing_input_detection_rate": 1.0,
    "adversarial_interception_rate": 1.0,
    "repeat_run_consistency": 1.0,
}

_BLOCK_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def load_cases(yaml_path: str) -> list[dict[str, Any]]:
    text = open(yaml_path, encoding="utf-8").read()
    cases: list[dict[str, Any]] = []
    sections = re.split(r"\n## ", text)
    for sec in sections[1:]:
        title = sec.split("\n", 1)[0].strip()
        blocks = _BLOCK_RE.findall(sec)
        if not blocks:
            continue
        payload = json.loads(blocks[0])
        checks_txt = sec
        cases.append({"title": title, "payload": payload, "checks": checks_txt})
    return cases


def run_cli(payload: dict, sub: str = "service") -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, CLI, sub],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=TOOLS_DIR, timeout=90)
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"ok": False,
                                 "error": {"message": f"non-JSON stdout: {proc.stdout[:300]}"}}
    return proc.returncode, env


def validate_output(doc: dict) -> bool:
    sys.path.insert(0, TOOLS_DIR)
    from _jsonschema import validate as js_validate  # noqa: PLC0415
    schema = json.load(open(os.path.join(SCHEMAS_DIR, "output.schema.json"), encoding="utf-8"))
    return not js_validate(doc, schema)


def walk_quantities(node, path="", out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        if "normalized_unit" in node and "acquisition_mode" in node \
                and "value" in node and "epistemic_tag" in node:
            out.append((path, node))
            return out
        for k, v in node.items():
            walk_quantities(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk_quantities(item, f"{path}[{i}]", out)
    return out


def check_group_isolation(body: dict, declared: set, card_id: str) -> bool:
    """All result quantities in a card bound to declared groups/time points."""
    card = next((c for c in body.get("evidence_cards", [])
                 if c.get("card_id") == card_id), None)
    if card is None:
        return False
    for path, q in walk_quantities(card):
        if ".results." in path or path.startswith("results."):
            if q.get("group_id") and q["group_id"] not in declared:
                return False
    return True


def main() -> int:
    cases = load_cases(os.path.join(SKILL_ROOT, "evals", "cases.yaml"))
    if len(cases) < 8:
        print(f"FATAL: expected >= 8 cases, found {len(cases)}")
        return 1

    results: list[dict[str, Any]] = []
    t0 = time.time()
    for case in cases:
        payload = case["payload"]
        title = case["title"]
        start = time.time()
        # corrupt-pdf case runs through the adapters CLI; everything else
        # through the full service pipeline.
        sub = "adapters" if "corrupt-pdf" in title else "service"
        rc, env = run_cli(payload, sub)
        elapsed = time.time() - start
        body = env.get("result") if env.get("ok") else {}
        status = body.get("status", "TOOL_ERROR")
        tool_error_clean = (not env.get("ok") and bool(env.get("error", {}).get("code")))

        structured_ok = False
        if status in ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
                      "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED"):
            structured_ok = validate_output(body)
        else:
            structured_ok = tool_error_clean

        # tool invocation: service ran real sub-tools, or a clean classified error
        tool_runs = (body.get("validation") or {}).get("tool_runs") or []
        tool_invoked = bool(tool_runs) or status in (
            "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED") \
            or tool_error_clean

        # evidence traceability: ref_ids used are a subset of input refs
        evidence_used = [e.get("ref_id") for e in body.get("evidence_used", [])]
        input_refs = {r.get("ref_id") for r in payload.get("evidence_refs", [])}
        input_refs |= {r.get("ref_id") for r in payload.get("data_refs", [])}
        evidence_ok = all(rid in input_refs for rid in evidence_used)

        # per-case semantic checks
        case_ok = True
        title_l = title.lower()

        if "multi-group-extraction" in title_l:
            t1 = next((c for c in body.get("evidence_cards", [])
                       if c.get("card_id", "").endswith(".t1")), None)
            if not t1:
                case_ok = False
            else:
                groups = {g["label"] for g in t1["experimental_groups"]}
                tps = {t["label"] for t in t1["time_points"]}
                if groups != {"Control", "MICP"}:
                    case_ok = False
                if not {"Day 7", "Day 14"} <= tps:
                    case_ok = False
                ucs = [q for p, q in walk_quantities(t1) if ".ucs" in p]
                control = sorted(q["value"] for q in ucs if q.get("group_id") == "g1")
                micp = sorted(q["value"] for q in ucs if q.get("group_id") == "g2")
                if control != [150.0, 210.0] or micp != [1200.0, 2500.0]:
                    case_ok = False

        if "od600-urease" in title_l:
            cards = body.get("evidence_cards", [])
            od600 = [q for p, q in walk_quantities(cards) if ".od600" in p]
            urease = [q for p, q in walk_quantities(cards) if ".urease_activity" in p]
            if not od600 or not urease:
                case_ok = False
            elif not all(q["normalized_unit"] == "OD600" for q in od600):
                case_ok = False
            elif not all(q["normalized_unit"] == "mmol_urea/min/OD" for q in urease):
                case_ok = False

        if "figure-digitized" in title_l:
            digi = [q for p, q in walk_quantities(body.get("evidence_cards", []))
                    if q.get("acquisition_mode") == "DIGITIZED_FROM_FIGURE"]
            if not digi:
                case_ok = False
            elif not all((q.get("digitization") or {}).get("error_estimate", 0) > 0
                         for q in digi):
                case_ok = False

        if "missing-unit" in title_l:
            amb = [q for p, q in walk_quantities(body.get("evidence_cards", []))
                   if q.get("acquisition_mode") == "AMBIGUOUS"]
            if not amb:
                case_ok = False
            elif not all(q["normalized_value"] is None and q["normalized_unit"] == ""
                         for q in amb):
                case_ok = False

        if "methods-results" in title_l:
            if "duplicates_contradictions" not in body:
                case_ok = False

        if "forged-doi" in title_l:
            verifs = body.get("doi_verifications", [])
            if not any(v.get("status") == "suspected_forged" for v in verifs):
                case_ok = False

        if "non-micp" in title_l:
            if status != "BLOCKED" or body.get("evidence_cards"):
                case_ok = False

        if "missing-document" in title_l:
            if status != "BLOCKED":
                case_ok = False
            fields = {m.get("field") for m in body.get("missing_inputs", [])}
            if not any("document" in f for f in fields):
                case_ok = False

        if "corrupt-pdf" in title_l:
            if env.get("ok") or (env.get("error") or {}).get("code") != "MEE-E303":
                case_ok = False

        if "group-smear" in title_l:
            iso = body.get("isolation_report") or {}
            if not iso:
                case_ok = False

        if "vague-request" in title_l:
            if status != "BLOCKED":
                case_ok = False
            fields = {m.get("field") for m in body.get("missing_inputs", [])}
            if "request" not in fields:
                case_ok = False

        # adversarial interception: forged DOI, group mixing, corrupt input
        adversarial = any(k in title_l for k in (
            "forged", "corrupt", "smear", "adversarial", "conflict"))
        if adversarial:
            intercepted = case_ok
        else:
            intercepted = True

        # missing-input detection: only cases whose *input* is missing (not a
        # quantity whose value is missing from the paper)
        wants_blocked = any(k in title_l for k in (
            "missing-document", "vague-request", "non-micp"))
        missing_ok = True
        if wants_blocked:
            missing_ok = (status == "BLOCKED")

        results.append({
            "title": title,
            "status": status,
            "structured_ok": structured_ok,
            "tool_invoked": tool_invoked,
            "evidence_ok": evidence_ok,
            "missing_ok": missing_ok,
            "intercepted": intercepted,
            "case_ok": case_ok,
            "elapsed_s": round(elapsed, 3),
        })

    elapsed_total = time.time() - t0

    n = len(results)

    def rate(attr: str) -> float:
        return sum(1 for r in results if r[attr]) / n

    metrics = {
        "structured_output_pass_rate": rate("structured_ok"),
        "tool_invocation_rate": rate("tool_invoked"),
        "evidence_traceability_rate": rate("evidence_ok"),
        "missing_input_detection_rate": rate("missing_ok"),
        "adversarial_interception_rate": rate("intercepted"),
        "repeat_run_consistency": 1.0,  # computed below
        "mean_failure_recovery_time": round(elapsed_total / n, 3),
    }

    # repeat-run consistency on the first service case
    first = next((c for c in cases if "corrupt-pdf" not in c["title"]), cases[0])
    _, e1 = run_cli(first["payload"], "service")
    _, e2 = run_cli(first["payload"], "service")
    metrics["repeat_run_consistency"] = 1.0 if json.dumps(e1, sort_keys=True) == \
        json.dumps(e2, sort_keys=True) else 0.0

    print("=" * 72)
    print(f"micp-evidence-extractor evals — {n} cases, {elapsed_total:.2f}s")
    print("=" * 72)
    for r in results:
        flags = []
        if not r["structured_ok"]:
            flags.append("STRUCT")
        if not r["tool_invoked"]:
            flags.append("TOOL")
        if not r["evidence_ok"]:
            flags.append("EVID")
        if not r["missing_ok"]:
            flags.append("MISSING")
        if not r["intercepted"]:
            flags.append("ADV")
        if not r["case_ok"]:
            flags.append("CASE")
        print(f"  [{r['status']:12s}] {r['title']:45s} {r['elapsed_s']:6.2f}s "
              f"{' | ' + ','.join(flags) if flags else ''}")
    print("-" * 72)
    ok = True
    for k, threshold in THRESHOLDS.items():
        v = metrics[k]
        passed = v >= threshold
        ok = ok and passed
        print(f"  {k:38s} {v:6.2f}  (threshold >= {threshold}) {'PASS' if passed else 'FAIL'}")
    print("=" * 72)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
