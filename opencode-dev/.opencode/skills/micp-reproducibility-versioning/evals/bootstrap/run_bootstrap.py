#!/usr/bin/env python3
"""Self-bootstrap: run the skill on itself — a real, complete reproduction loop.

This is the skill's own bootstrap test (SKILL.md section 九): a demo MICP study
is set up and the skill's tools reproduce it end-to-end:

  1. create a Reproduction Manifest
  2. lock the environment
  3. record inputs (hashes of data/raw)
  4. execute the pipeline
  5. save artifacts
  6. re-run in the same tree and compare output hashes
  7. re-run in a *new* directory (clone) and compare again
  8. emit a diff report
  9. red-team scan: look for untracked files, unlocked deps, raw overwrites,
     non-deterministic RNG, version omissions

Everything is executed through the real `cli.py` subprocesses. The artifacts
(manifest, provenance log, environment report, diff report) are persisted into
the current directory under `provenance/` so they can be inspected.

Exit code 0 when the loop is fully consistent.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS_DIR = os.path.join(SKILL_ROOT, "tools", "mrv")
CLI = os.path.join(TOOLS_DIR, "cli.py")
OUT_DIR = os.path.join(SKILL_ROOT, "evals", "bootstrap", "results")

TS = "2026-08-07T12:00:00Z"
PROJECT = "panshi-bootstrap-demo"

SUMMARY_CODE = (
    "import csv;"
    "rows=list(csv.DictReader(open('data/raw/ucs.csv')));"
    "m={}\n"
    "for r in rows:\n"
    " m.setdefault(r['treatment'],[]).append(float(r['ucs_mpa']))\n"
    "with open('data/processed/summary.csv','w') as out:\n"
    " for k,v in sorted(m.items()):\n"
    "  out.write(f'{k},{sum(v)/len(v)}'+chr(10))\n"
)
SUMMARY_CMD = ('python -c "import base64;'
               'exec(base64.b64decode(\'%s\').decode())"' %
               base64.b64encode(SUMMARY_CODE.encode()).decode())


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_demo(root: str) -> None:
    for d in ("data/raw", "data/interim", "data/processed", "data/external",
              "artifacts", "reports", "provenance"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    raw = os.path.join(root, "data", "raw", "ucs.csv")
    with open(raw, "w", encoding="utf-8") as fh:
        fh.write("specimen,treatment,ucs_mpa\nA1,ctrl,1.0\nA2,ctrl,1.3\n"
                 "B1,micp,3.0\nB2,micp,3.5\n")
    os.chmod(raw, stat.S_IREAD | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    lock = os.path.join(root, "requirements.txt")
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write("numpy==1.26.0\npandas==2.1.0\n")


def run_cli(root: str, action: str, **extra) -> dict:
    payload = {
        "task_id": f"bootstrap-{action}",
        "project_id": PROJECT,
        "request": f"bootstrap {action}",
        "action": action,
        "root": root,
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": TS,
        "risk_level": "low",
        "human_approval_state": "not_required",
        "seed_policy": "reuse",
        "random_seed": 20260807,
        "parameters": {"curing_temp_c": 25, "reagent_mm": 0.5, "batch": "B01"},
    }
    payload.update(extra)
    proc = subprocess.run([sys.executable, CLI, action],
                          input=json.dumps(payload), capture_output=True, text=True,
                          cwd=TOOLS_DIR, timeout=120)
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON stdout for {action}: {proc.stdout[:300]}\n{proc.stderr[:300]}")
    return env


def copy_tree(src: str, dst: str) -> None:
    """Clone the demo tree (excluding governance outputs) to a new directory."""
    shutil.copytree(src, dst,
                    ignore=shutil.ignore_patterns("provenance", "__pycache__"))


def main() -> int:
    print("=" * 72)
    print("micp-reproducibility-versioning — SELF-BOOTSTRAP")
    print("=" * 72)

    base = tempfile.mkdtemp(prefix="mrv-bootstrap-")
    run_a = os.path.join(base, "run-a")
    make_demo(run_a)

    # 1–5. first run: manifest, lock env, record inputs, execute, save artifacts
    print("\n[1] reproduce run A (fresh tree)…")
    e1 = run_cli(run_a, "reproduce",
                 commands=[{"id": "write-summary", "cmd": SUMMARY_CMD, "cwd": ".",
                            "expected_outputs": ["data/processed/summary.csv"]}],
                 constraints={"timeout_sec": 60})
    assert e1["ok"], e1
    r1 = e1["result"]
    m1 = r1["reproduction_manifest"]
    print(f"    manifest_id        = {m1['manifest_id']}")
    print(f"    inputs             = {[i['path'] for i in m1['inputs']]}")
    print(f"    outputs            = {[o['path'] for o in m1['outputs']]}")
    print(f"    parameter digest   = {r1['hashes']['parameters_digest'][:16]}…")
    print(f"    seed               = {r1['seed']['value']}")
    print(f"    identity           = {m1['versions']['git_commit'][:16]}…")
    print(f"    lineage hops       = {len(r1['data_lineage'])}")
    print(f"    raw protection ok  = "
          f"{[c for c in r1['reproducibility_checks'] if c['check']=='raw_write_protection'][0]['passed']}")

    # 6. re-run in the same tree and compare output hashes
    print("\n[2] reproduce run A (same tree, rerun)…")
    e2 = run_cli(run_a, "reproduce",
                 commands=[{"id": "write-summary", "cmd": SUMMARY_CMD, "cwd": ".",
                            "expected_outputs": ["data/processed/summary.csv"]}],
                 constraints={"timeout_sec": 60})
    assert e2["ok"], e2
    r2 = e2["result"]
    same = json.dumps(r1["reproduction_manifest"], sort_keys=True) == \
        json.dumps(r2["reproduction_manifest"], sort_keys=True)
    print(f"    manifest identical = {same}")
    print(f"    rerun identical    = {r2['identical_to_previous']}")
    assert same and r2["identical_to_previous"], "rerun drifted!"

    # 7. re-run in a new directory (clone) and compare hashes
    run_b = os.path.join(base, "run-b")
    copy_tree(run_a, run_b)
    print("\n[3] reproduce run B (fresh clone of inputs, same code)…")
    e3 = run_cli(run_b, "reproduce",
                 commands=[{"id": "write-summary", "cmd": SUMMARY_CMD, "cwd": ".",
                            "expected_outputs": ["data/processed/summary.csv"]}],
                 constraints={"timeout_sec": 60})
    assert e3["ok"], e3
    r3 = e3["result"]
    m3 = r3["reproduction_manifest"]
    h1_in = {i["path"]: i["hash"] for i in m1["inputs"]}
    h3_in = {i["path"]: i["hash"] for i in m3["inputs"]}
    h1_out = {o["path"]: o["hash"] for o in m1["outputs"]}
    h3_out = {o["path"]: o["hash"] for o in m3["outputs"]}
    print(f"    input hashes equal = {h1_in == h3_in}")
    print(f"    output hashes equal= {h1_out == h3_out}")
    assert h1_in == h3_in and h1_out == h3_out, "clone reproduction diverged!"

    # 8. diff report: baseline manifest (run A) vs current (run B)
    print("\n[4] diff report (run A baseline vs run B)…")
    baseline_id = m1["manifest_id"]
    e4 = run_cli(run_a, "diff",
                 previous_manifest=f"provenance/manifests/{baseline_id}.json")
    assert e4["ok"], e4
    d4 = e4["result"]
    print(f"    identical = {d4['identical']}, {d4['difference_count']} difference(s)")
    assert d4["identical"], f"baseline drifted: {d4['differences'][:3]}"

    # 9. red-team scan
    print("\n[5] red-team scan…")
    red = red_team_scan(run_a)
    for finding in red:
        print(f"    [{finding['severity']:7s}] {finding['finding']}")
        if finding.get("detail"):
            print(f"            {finding['detail'][:120]}")

    # persist artifacts into the repo's bootstrap/results dir
    os.makedirs(OUT_DIR, exist_ok=True)
    shutil.copy2(os.path.join(run_a, "provenance", "reproduction-manifest.json"),
                 os.path.join(OUT_DIR, "reproduction-manifest.json"))
    shutil.copy2(os.path.join(run_a, "provenance", "provenance.log"),
                 os.path.join(OUT_DIR, "provenance.log"))
    shutil.copy2(os.path.join(run_a, "provenance", "environment.json"),
                 os.path.join(OUT_DIR, "environment.json"))
    for f in os.listdir(os.path.join(run_a, "provenance", "manifests")):
        shutil.copy2(os.path.join(run_a, "provenance", "manifests", f),
                     os.path.join(OUT_DIR, f))
    with open(os.path.join(OUT_DIR, "bootstrap-report.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "ts": TS,
            "project": PROJECT,
            "run_a_manifest": m1["manifest_id"],
            "run_a_manifest_identical_on_rerun": same,
            "clone_input_hashes_equal": h1_in == h3_in,
            "clone_output_hashes_equal": h1_out == h3_out,
            "diff_identical": d4["identical"],
            "red_team": red,
            "persisted_to": os.path.relpath(OUT_DIR, SKILL_ROOT),
        }, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 72)
    print(f"BOOTSTRAP PASS — artifacts persisted to {os.path.relpath(OUT_DIR, SKILL_ROOT)}")
    print("=" * 72)
    return 0


def red_team_scan(root: str) -> list[dict]:
    """Adversarial pass: hunt for the failures the skill must prevent.

    Scans for: untracked/unfingerprinted files, unlocked dependencies, raw
    overwrites, non-deterministic RNG traces, and missing version records.
    """
    findings: list[dict] = []

    manifest_path = os.path.join(root, "provenance", "reproduction-manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8")) if os.path.isfile(manifest_path) else {}

    # 1. raw overwrite / write protection
    raw_files = []
    for dirpath, _d, files in os.walk(os.path.join(root, "data", "raw")):
        for f in files:
            raw_files.append(os.path.join(dirpath, f))
    writable = [r for r in raw_files if os.access(r, os.W_OK)]
    if writable:
        findings.append({"severity": "critical",
                         "finding": "raw data is writable (write protection breached)",
                         "detail": ", ".join(os.path.relpath(w, root) for w in writable)})
    else:
        findings.append({"severity": "ok",
                         "finding": "raw data read-only protection intact"})

    # 2. manifest hash coverage: every raw file must be in manifest inputs
    recorded = {i["path"]: i["hash"] for i in manifest.get("inputs", [])}
    missing_in_manifest = [
        os.path.relpath(r, root).replace("\\", "/") for r in raw_files
        if os.path.relpath(r, root).replace("\\", "/") not in recorded]
    if missing_in_manifest:
        findings.append({"severity": "high",
                         "finding": "raw files missing from manifest inputs (untraceable)",
                         "detail": ", ".join(missing_in_manifest)})
    else:
        findings.append({"severity": "ok",
                         "finding": "all raw inputs are recorded in the manifest"})

    # 3. dependency locking
    lockfiles = [f for f in ("bun.lock", "package-lock.json", "pnpm-lock.yaml",
                             "requirements.txt", "Pipfile.lock", "poetry.lock", "uv.lock")
                 if os.path.isfile(os.path.join(root, f))]
    if not lockfiles:
        findings.append({"severity": "medium",
                         "finding": "no dependency lockfile present; dependency drift unversioned"})
    else:
        findings.append({"severity": "ok",
                         "finding": f"dependency lockfile(s) present: {', '.join(lockfiles)}"})

    # 4. non-deterministic RNG traces in command stubs (nothing should be ambient)
    ambient_rng = []
    for dirpath, _d, files in os.walk(root):
        for f in files:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf-8", errors="ignore").read()
            if "import random" in src and "random.seed(" not in src and \
                    "Pcg32" not in src and "splitmix64" not in src:
                ambient_rng.append(os.path.relpath(os.path.join(dirpath, f), root))
    if ambient_rng:
        findings.append({"severity": "medium",
                         "finding": "unseeded random module usage (non-deterministic)",
                         "detail": ", ".join(ambient_rng)})

    # 5. version coverage in the manifest
    versions = manifest.get("versions", {})
    required_versions = ["git_commit", "skill_version", "controller_version",
                         "constitution_version", "schema"]
    omitted = [k for k in required_versions if not versions.get(k)]
    if omitted:
        findings.append({"severity": "medium",
                         "finding": f"version record omitted: {', '.join(omitted)}"})
    else:
        findings.append({"severity": "ok", "finding": "version records complete"})

    # 6. git identity
    git_present = versions.get("git_active")
    if git_present is False:
        findings.append({"severity": "high",
                         "finding": "project is not under git version control; "
                                    "fingerprint identity only, rollback is manual"})

    # 7. untracked files (present on disk but not hashed anywhere)
    all_hashed = set(recorded) | {o["path"] for o in manifest.get("outputs", [])}
    loose = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("provenance", "__pycache__")]
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace("\\", "/")
            if rel not in all_hashed and not rel.startswith("provenance/"):
                loose.append(rel)
    if loose:
        findings.append({"severity": "low",
                         "finding": "files on disk not hashed by the manifest",
                         "detail": ", ".join(loose[:10])})

    return findings


if __name__ == "__main__":
    sys.exit(main())
