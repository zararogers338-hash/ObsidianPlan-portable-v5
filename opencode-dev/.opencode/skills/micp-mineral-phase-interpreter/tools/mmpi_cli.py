#!/usr/bin/env python3
"""micp-mineral-phase-interpreter CLI.

Contract (mirrors obsidian-state-manager):
  stdin   one JSON object conforming to schemas/input.schema.json
  stdout  one JSON object conforming to schemas/output.schema.json
  stderr  human-readable progress/diagnostics (never protocol data)
  exit    0 always when an output envelope was produced (status field carries
          the outcome); 2 only when stdin could not be parsed as JSON at all.

No repo paths are hardcoded; tests always inject schema_dir via env var
OMM_SCHEMA_DIR when needed. The CLI itself resolves schemas relative to the
skill root.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mmpi.errors import make_error  # noqa: E402
from mmpi.models import SKILL_NAME, SKILL_VERSION  # noqa: E402
from mmpi.service import handle  # noqa: E402

DEFAULT_SCHEMA_DIR = str(Path(__file__).resolve().parent.parent / "schemas")


def _minimal_failure_envelope(message: str) -> dict:
    return {
        "contract_version": "1.0",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "BLOCKED",
        "summary": message,
        "action": None,
        "project_id": None,
        "task_id": None,
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "results": {},
        "validation": {"input_schema": "failed", "output_schema": "pending",
                       "self_check": "not_run", "checks": []},
        "provenance": {"started_at": None, "completed_at": None,
                       "skill_version": SKILL_VERSION,
                       "sources": ["references/sources.md"], "audit_log": None},
        "errors": [make_error("OMM-E101", message).to_dict()],
    }


def _resolve_schema_dir(argv: list[str]) -> str:
    if "--schema-dir" in argv:
        i = argv.index("--schema-dir")
        if i + 1 >= len(argv):
            print("--schema-dir requires a path argument", file=sys.stderr)
            raise SystemExit(2)
        return str(Path(argv[i + 1]).resolve())
    env = os.environ.get("OMM_SCHEMA_DIR")
    if env:
        return env
    return DEFAULT_SCHEMA_DIR


def _finalize_minimal(out: dict, schema_dir: str) -> dict:
    """Validate the minimal failure envelope against the output schema so the
    failure path reports the same contract status as the success path."""
    try:
        from mmpi.validate import validate_output
        issues = validate_output(out, schema_dir)
        out["validation"]["output_schema"] = "passed" if len(issues) == 0 else "failed"
    except Exception:
        out["validation"]["output_schema"] = "failed"
    return out


def main(argv: list[str]) -> int:
    schema_dir = _resolve_schema_dir(argv)
    raw_text = sys.stdin.read()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        out = _finalize_minimal(_minimal_failure_envelope(
            f"stdin 不是合法 JSON: {exc.msg} at line {exc.lineno} col {exc.colno}"), schema_dir)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if not isinstance(payload, dict):
        out = _finalize_minimal(_minimal_failure_envelope("stdin JSON 必须是对象"), schema_dir)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    try:
        out = handle(payload, schema_dir=schema_dir)
    except Exception as exc:  # last-resort envelope (must still pass output schema)
        out = _minimal_failure_envelope(f"内部错误: {exc!r}")
        out["status"] = "FAILED"
        out["errors"] = [make_error("OMM-E602", f"内部错误: {exc!r}").to_dict()]
        out = _finalize_minimal(out, schema_dir)

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
