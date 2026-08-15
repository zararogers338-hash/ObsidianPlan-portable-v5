"""CLI entry for micp-literature-scout.

Reads one JSON object from stdin (input.schema.json), writes one JSON object to
stdout (output.schema.json — always valid, success or failure). Protocol data
only on stdout; diagnostics on stderr.

Usage:
    python tools/literature_scout.py < input.json > output.json
    python tools/literature_scout.py --offline < input.json > output.json
    python tools/literature_scout.py --offline --verbose < input.json

Flags:
    --offline      force offline-fixture mode (no network, deterministic; CI-safe)
    --trace-dir D  override trace log directory
    --verbose      echo the output envelope to stderr for diagnostics
    --version      print skill version and exit
    --help         print this help and exit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from micp_lit.service import (  # noqa: E402
    CONTRACT_VERSION,
    SKILL_NAME,
    SKILL_VERSION,
    SkillService,
)
from micp_lit.models import OutputStatus  # noqa: E402


def _build_failure(summary: str, detail: dict) -> dict:
    return {
        "status": OutputStatus.FAILED.value,
        "summary": summary,
        "findings": [{"statement": summary, "label": "OBSERVED"}],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {"self_check_passed": False, "output_schema_valid": False, "checks": []},
        "provenance": {
            "skill_name": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "contract_version": CONTRACT_VERSION,
            "tool_version": SKILL_VERSION,
            "timestamp": "",
        },
        "errors": [{"code": "MLS-E100", "message": summary, "detail": detail}],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="literature_scout.py", description=__doc__)
    parser.add_argument("--offline", action="store_true", help="force offline-fixture mode")
    parser.add_argument("--trace-dir", type=str, default=None, help="override trace log dir")
    parser.add_argument("--verbose", action="store_true", help="echo envelope to stderr")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args, _rest = parser.parse_known_args(argv)

    if args.version:
        print(f"{SKILL_NAME} {SKILL_VERSION} (contract {CONTRACT_VERSION})")
        return 0

    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw or not raw.strip():
        out = _build_failure("stdin 为空; 需要一个 JSON 对象", {"hint": "input.schema.json"})
        print(json.dumps(out, ensure_ascii=False))
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        out = _build_failure(f"stdin 不是合法 JSON: {exc}", {"error": str(exc)})
        print(json.dumps(out, ensure_ascii=False))
        return 2

    if args.trace_dir:
        payload["trace_dir"] = args.trace_dir

    service = SkillService(offline=args.offline)
    try:
        out = service.run(payload)
    except Exception as exc:  # noqa: BLE001 — never crash the controller
        out = _build_failure(f"Skill 内部异常: {type(exc).__name__}: {exc}", {"exc": str(exc)})
        print(json.dumps(out, ensure_ascii=False))
        return 1

    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if args.verbose:
        sys.stderr.write(f"status={out.get('status')} summary={out.get('summary')}\n")
    return 0 if out.get("status") in ("SUCCESS", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
