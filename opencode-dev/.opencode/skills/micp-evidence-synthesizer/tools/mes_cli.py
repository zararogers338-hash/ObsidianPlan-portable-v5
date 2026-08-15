#!/usr/bin/env python3
"""micp-evidence-synthesizer CLI (MES).

Contract (mirrors sibling skills, e.g. obsidian-state-manager):
  stdin   one JSON object conforming to schemas/input.schema.json
  stdout  one JSON object conforming to schemas/output.schema.json
  stderr  human-readable diagnostics only (never protocol data)
  exit    0 when an output envelope was produced (status field carries the
          outcome); 2 only when stdin is not valid JSON at all.

Usage:
  python3 tools/mes_cli.py [--root <skill-root>] < input.json > output.json
  python3 tools/mes_cli.py --validate-schema <input.json>   # exit 0/1

The skill root is auto-detected from this file's location (…/skills/
micp-evidence-synthesizer/), so schemas/ resolves without configuration.
No network, no writes, fully offline. Deterministic given the same input
(digest and timestamps are the only time-dependent fields).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running the tools package directly without installation.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mes.service import MesService  # noqa: E402
from mes.models import SKILL_NAME, SKILL_VERSION  # noqa: E402


def _detect_root() -> Path:
    # tools/mes_cli.py  ->  skill root is two levels up
    return HERE.parent


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
        "synthesis": None,
        "validation": {"input_schema": "failed", "output_schema": "pending",
                       "self_check": "not_run"},
        "provenance": {"started_at": None, "completed_at": None,
                       "skill_version": SKILL_VERSION, "tool_versions": {},
                       "input_digest": None},
        "errors": [{"code": "OES-E101", "message": message,
                    "detail": {}, "retryable": False}],
    }


def main(argv: list[str]) -> int:
    root = _detect_root()
    if "--validate-schema" in argv:
        idx = argv.index("--validate-schema")
        target = argv[idx + 1] if idx + 1 < len(argv) else None
        if not target:
            print("--validate-schema requires a JSON file path", file=sys.stderr)
            return 2
        try:
            raw = Path(target).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {target}: {exc}", file=sys.stderr)
            return 2
        from mes import jsonschema as _js
        schema = json.loads((root / "schemas" / "input.schema.json").read_text(encoding="utf-8"))
        issues = _js.validate_json_str(raw, schema)
        if issues:
            for i in issues:
                print(f"{i.path}: {i.message}", file=sys.stderr)
            return 1
        print("input schema: OK", file=sys.stdout)
        return 0

    raw_text = sys.stdin.read()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        out = _minimal_failure_envelope(
            f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}")
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if not isinstance(payload, dict):
        out = _minimal_failure_envelope("stdin JSON must be an object")
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    service = MesService(skill_root=str(root))
    out = service.handle(payload)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
