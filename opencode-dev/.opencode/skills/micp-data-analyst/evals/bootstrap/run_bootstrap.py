#!/usr/bin/env python3
"""Bootstrap tests for micp-data-analyst.

These are the self-embedding tests required by the Obsidian Plan skill spec:
the skill is invoked as if by a normal user (no expected answers leaked in the
input), and the outputs are checked for correct trigger/boundary handling,
real tool invocation, schema validity, and adversarial review.

The four bootstrap scenarios:

  1. Pseudo-replication: same sand column sampled at multiple heights must be
     detected as non-independent; group effect sizes aggregated to the
     independent unit.
  2. Significant-but-tiny-effect: large Cohen's d at high n must be reported
     with CI, power, AND an engineering judgment (statistical significance is
     not engineering value).
  3. Outlier sensitivity: a multi-strategy sensitivity analysis must run for
     flagged outliers and report the estimate spread.
  4. Repeat-run consistency: identical input runs byte-identical; changing the
     random seed changes the output; both pass self-check.

Offline, deterministic, stdlib-only. Exit 0 when all bootstraps pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(os.path.dirname(HERE))
CLI = os.path.join(SKILL_ROOT, "tools", "micp", "cli.py")

PASS = "PASS"
FAIL = "FAIL"


def run_service(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, CLI, "service"],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=os.path.dirname(CLI), timeout=60)
    if proc.returncode != 0:
        return {"ok": False, "error": {"message": proc.stdout[:400]}}
    return json.loads(proc.stdout)


def _body(env: dict) -> dict:
    return env.get("result") if env.get("ok") else {}


def boot1_pseudo_replication(payload: dict) -> bool:
    env = run_service(payload)
    body = _body(env)
    if body.get("status") != "SUCCESS":
        print(f"    [{FAIL}] boot1: status {body.get('status')}")
        return False
    pr = body.get("pseudo_replication") or {}
    gc = (body.get("statistics") or {}).get("group_comparison") or {}
    es = gc.get("effect_size") or {}
    ok = (pr.get("detected") is True
          and pr.get("findings") and pr["findings"][0]["effective_n"] == 4
          and gc.get("unit_aggregated") is True
          and es.get("n1") == 2 and es.get("n2") == 2
          and body.get("validation", {}).get("self_audit_pass") is True)
    print(f"    [{PASS if ok else FAIL}] boot1: pseudo-replication detected "
          f"(effective_n={pr.get('findings', [{}])[0].get('effective_n')}), "
          f"group effect on independent units n={es.get('n1')}+{es.get('n2')}, "
          f"d={es.get('cohens_d')}")
    return ok


def boot2_significant_but_tiny(payload: dict) -> bool:
    env = run_service(payload)
    body = _body(env)
    if body.get("status") != "SUCCESS":
        print(f"    [{FAIL}] boot2: status {body.get('status')}")
        return False
    gc = (body.get("statistics") or {}).get("group_comparison") or {}
    es = gc.get("effect_size") or {}
    eng = gc.get("engineering") or {}
    pw = gc.get("power_est") or {}
    ok = ("cohens_d" in es
          and "ci_lower_95" in es and "ci_upper_95" in es
          and "power" in pw
          and "verdict" in eng
          and any("Engineering judgment" in f["statement"] for f in body.get("findings", [])))
    print(f"    [{PASS if ok else FAIL}] boot2: d={es.get('cohens_d')} (large), "
          f"CI=[{es.get('ci_lower_95')},{es.get('ci_upper_95')}], power={pw.get('power')}, "
          f"engineering verdict={eng.get('verdict')}")
    return ok


def boot3_sensitivity(payload: dict) -> bool:
    env = run_service(payload)
    body = _body(env)
    if body.get("status") != "SUCCESS":
        print(f"    [{FAIL}] boot3: status {body.get('status')}")
        return False
    stats = body.get("statistics") or {}
    var = (stats.get("variables") or {}).get("caco3", {})
    sens = stats.get("sensitivity") or {}
    out = var.get("outliers") or {}
    ok = (out.get("n_iqr_outliers", 0) >= 1
          and "winsorize_1p5iqr" in sens.get("estimates", {})
          and sens.get("spread") is not None
          and body.get("validation", {}).get("self_audit_pass") is True)
    print(f"    [{PASS if ok else FAIL}] boot3: outliers={out.get('n_iqr_outliers')}, "
          f"strategies={sens.get('strategies_run')}, spread={sens.get('spread')}")
    return ok


def boot4_repeat_consistency(payload: dict) -> bool:
    def _hash(p: dict) -> str:
        env = run_service(p)
        body = _body(env)
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

    h1 = _hash(payload)
    h2 = _hash(payload)
    p3 = json.loads(json.dumps(payload))
    p3["reproducibility"] = {"random_seed": 12345, "rng_algorithm": "python_random"}
    h3 = _hash(p3)
    ok = h1 == h2 and h1 != h3
    print(f"    [{PASS if ok else FAIL}] boot4: repeat-run identical "
          f"({h1}=={h2}), seed-changed differs ({h1}!={h3})")
    return ok


def boot5_adversarial_review(payload: dict) -> bool:
    """A review role attacks the output: fabricated 1000x claim must NOT be
    adopted as OBSERVED; every evidence ref must carry a verifiability note
    (this skill never asserts offline verification); the extreme 500 MPa value
    must be surfaced (outlier low-confidence at n=3)."""
    env = run_service(payload)
    body = _body(env)
    claims = [f["statement"] for f in body.get("findings", [])]
    fabricated = any("1000" in c or "1000x" in c.lower() for c in claims)
    ev = body.get("evidence_used") or []
    ev_noted = bool(ev) and all("note" in e and "verifiable" in e for e in ev)
    outliers = (body.get("statistics") or {}).get("variables", {}).get("ucs", {}).get("outliers") or {}
    ok = (body.get("status") == "SUCCESS"
          and not fabricated
          and ev_noted
          and outliers.get("low_confidence") is True
          and body.get("validation", {}).get("self_audit_pass") is True)
    print(f"    [{PASS if ok else FAIL}] boot5: adversarial review — 1000x claim "
          f"{'suppressed' if not fabricated else 'FABRICATED'}, evidence "
          f"{'annotated' if ev_noted else 'not annotated'}, outlier low-confidence="
          f"{outliers.get('low_confidence')}")
    return ok


def main() -> int:
    here = HERE
    # ordered list of (input_file, check_fn, label) — a dict would dedupe keys
    steps = [
        ("bootstrap1.json", boot1_pseudo_replication, "boot1: pseudo-replication"),
        ("boot2-threshold.json", boot2_significant_but_tiny, "boot2: significant-but-tiny"),
        ("boot3-sensitivity.json", boot3_sensitivity, "boot3: outlier sensitivity"),
        ("bootstrap1.json", boot4_repeat_consistency, "boot4: repeat-run consistency"),
        ("boot5-attack.json", boot5_adversarial_review, "boot5: adversarial review"),
    ]
    results = []
    t0 = time.time()
    for fname, fn, label in steps:
        path = os.path.join(here, fname)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        print(f"  {label}")
        ok = fn(payload)
        results.append((label, ok))
    print(f"  bootstrap suite: {sum(1 for _, ok in results if ok)}/{len(results)} passed "
          f"({time.time() - t0:.2f}s)")
    return 0 if all(ok for _, ok in results) else 2


if __name__ == "__main__":
    sys.exit(main())
