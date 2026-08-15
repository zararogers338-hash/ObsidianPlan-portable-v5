#!/usr/bin/env python3
"""micp-scaleup-injection-engineer CLI.

Contract (mirrors the project convention):
  stdin   one JSON object conforming to schemas/input.schema.json
  stdout  one JSON object conforming to schemas/output.schema.json
  stderr  human-readable diagnostics (never protocol data)
  exit    0 when an output envelope was produced (status carries the outcome);
          2 only when stdin could not be parsed as JSON at all.

Subcommands (kept for ergonomics; the primary mode is stdin/stdout):
  scaleup < input.json > output.json   full service pipeline
  selfcheck <json-file>                validate a JSON file against the output schema
  schema                                print the input schema (for tooling)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from msi.errors import OpError, OpErrorCode  # noqa: E402
from msi.models import CONTRACT_VERSION, SKILL_NAME, SKILL_VERSION  # noqa: E402
from msi.observability import configure  # noqa: E402


def _minimal_failure_envelope(message: str) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
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
        "validation": {"input_schema": "failed", "output_schema": "pending",
                       "self_check": "not_run", "checks": []},
        "provenance": {"started_at": None, "completed_at": None,
                       "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                       "host": None, "log_tail": [], "artifacts_written": []},
        "errors": [{"code": OpErrorCode.INPUT_SCHEMA_VIOLATION.code,
                    "message": message, "detail": {}, "retryable": False}],
        # §八 domain fields
        "scale_level": None, "site_assumptions": [], "similarity_matrix": None,
        "non_scalable_factors": [], "injection_layout": None, "injection_schedule": None,
        "material_balance": None, "pressure_constraints": None, "monitoring_plan": None,
        "stop_conditions": [], "fallback_plan": None, "environmental_requirements": None,
    }


def _resolve_artifact_dir(argv: list[str]) -> str | None:
    if "--artifact-dir" in argv:
        i = argv.index("--artifact-dir")
        if i + 1 < len(argv):
            return str(Path(argv[i + 1]).expanduser().resolve())
    env = os.environ.get("MSI_ARTIFACT_DIR")
    return env


def _run_scaleup(payload: dict, artifact_dir: str | None) -> dict:
    from msi.service import ScaleUpService

    if artifact_dir:
        Path(artifact_dir).mkdir(parents=True, exist_ok=True)
    svc = ScaleUpService(artifact_dir=artifact_dir)
    out = svc.handle(payload)
    out["provenance"]["log_tail"] = svc.log.recent(12)
    if artifact_dir:
        out["provenance"]["artifacts_written"] = out.get("provenance", {}).get("artifacts_written", [])
    return out


def _selfcheck(path: str) -> int:
    from msi.validate import validate_output

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    issues = validate_output(value)
    if issues:
        for p, m in issues:
            print(f"{p}: {m}", file=sys.stderr)
        return 1
    print("output schema: OK")
    return 0


def main(argv: list[str]) -> int:
    log_level = "info"
    if "--log-level" in argv:
        i = argv.index("--log-level")
        if i + 1 < len(argv):
            log_level = argv[i + 1]
    configure(level=log_level)
    artifact_dir = _resolve_artifact_dir(argv)

    cmd_args = [a for a in argv if not a.startswith("--")]
    sub = cmd_args[0] if cmd_args else "scaleup"

    if sub == "schema":
        schema = (HERE.parent / "schemas" / "input.schema.json").read_text(encoding="utf-8")
        sys.stdout.write(schema + "\n")
        return 0
    if sub == "selfcheck":
        if len(cmd_args) < 2:
            print("selfcheck requires a JSON file path", file=sys.stderr)
            return 1
        return _selfcheck(cmd_args[1])

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

    out = _run_scaleup(payload, artifact_dir)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
