"""Shared fixtures for micp-reproducibility-versioning tests.

All fixtures are offline and deterministic. `run_cli` executes the real CLI
over stdin and asserts the exit code, proving the tools run for real.
`make_sandbox` builds a temp project tree with a protected data/raw layer.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "mrv")
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")


def run_cli(name: str, payload: dict, expect_exit: int = 0) -> dict:
    """Run a tool over stdin, return its envelope dict, assert the exit code."""
    script = os.path.join(TOOLS_DIR, "cli.py")
    proc = subprocess.run(
        [sys.executable, script, name],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=TOOLS_DIR,
        timeout=90,
    )
    assert proc.returncode == expect_exit, (
        f"{name} exited {proc.returncode}, expected {expect_exit}\n"
        f"stderr: {proc.stderr[-800:]}\nstdout: {proc.stdout[-800:]}")
    return json.loads(proc.stdout)


def make_sandbox(tmp_path, *, protect_raw: bool = True) -> str:
    """A temp project tree with data/raw (optionally read-only) + layers."""
    root = str(tmp_path)
    for d in ("data/raw", "data/interim", "data/processed", "data/external",
              "artifacts", "reports", "provenance"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    raw = os.path.join(root, "data", "raw", "ucs.csv")
    with open(raw, "w", encoding="utf-8") as fh:
        fh.write("specimen,treatment,ucs_mpa\nA1,ctrl,1.0\nA2,ctrl,1.3\n"
                 "B1,micp,3.0\nB2,micp,3.5\n")
    if protect_raw:
        os.chmod(raw, stat.S_IREAD | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return root


def base_payload(root: str, **overrides) -> dict:
    payload = {
        "task_id": "test-01",
        "project_id": "panshi-demo",
        "request": "复现 MICP UCS 分析并生成清单、锁定环境、记录 provenance",
        "action": "reproduce",
        "root": root,
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T08:00:00Z",
        "risk_level": "low",
        "human_approval_state": "not_required",
        "seed_policy": "reuse",
        "random_seed": 42,
        "parameters": {"curing_temp_c": 25},
    }
    payload.update(overrides)
    return payload


def gen_cmd(code: str) -> str:
    """Wrap a python snippet as a shell command without escaping pain."""
    import base64
    b64 = base64.b64encode(code.encode()).decode()
    return f'python -c "import base64;exec(base64.b64decode(\'{b64}\').decode())"'


WRITE_SUMMARY = gen_cmd(
    "import csv;"
    "rows=list(csv.DictReader(open('data/raw/ucs.csv')));"
    "m={}\n"
    "for r in rows:\n"
    " m.setdefault(r['treatment'],[]).append(float(r['ucs_mpa']))\n"
    "with open('data/processed/summary.csv','w') as out:\n"
    " for k,v in sorted(m.items()):\n"
    "  out.write(f'{k},{sum(v)/len(v)}'+chr(10))\n"
)
