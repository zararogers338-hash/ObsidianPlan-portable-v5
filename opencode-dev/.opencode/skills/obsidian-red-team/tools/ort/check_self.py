"""Output self-checker: validates a review envelope against output.schema.json.

Usage: python tools/ort/cli.py check-self < review_output.json
Result: {ok, valid, issues}
"""

from __future__ import annotations

import json
import os
from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("check-self: validating output against output.schema.json")
    # Accept either the raw ORT output or the CLI envelope {ok, tool, result}.
    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], dict) \
            and "status" in payload["result"]:
        payload = payload["result"]
    if "status" not in payload:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "check-self: payload is not an ORT output envelope (missing status)")

    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "schemas", "output.schema.json")
    if not os.path.isfile(schema_path):
        raise ToolError("ORT-E301", f"schema file not found: {schema_path}", exit_code=4)
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)

    issues: list[str] = []
    try:
        from _jsonschema import validate_with_schema
        issues = validate_with_schema(payload, schema)
    except Exception:  # noqa: BLE001
        try:
            import jsonschema  # type: ignore
            v = jsonschema.Draft202012Validator(schema)
            issues = [f"{e.message} at {'/'.join(map(str, e.path))}" for e in sorted(
                v.iter_errors(payload), key=lambda e: list(e.path))]
        except Exception:  # noqa: BLE001
            issues = ["schema engine unavailable"]

    # Hard invariant: BLOCKING findings force status != SUCCESS and a
    # non-approving state recommendation.
    blocking_count = len(payload.get("blocking_findings") or [])
    status = payload.get("status")
    rec = payload.get("state_recommendation", {}).get("recommendation")
    if blocking_count > 0 and status == "SUCCESS":
        issues.append("invariant: BLOCKING findings present but status == SUCCESS")
    if blocking_count > 0 and rec in ("APPROVE", "NO_OBJECTION"):
        issues.append(f"invariant: BLOCKING findings present but recommendation == {rec}")

    # Every blocking_findings entry must be present in findings.
    finding_ids = {f.get("finding_id") for f in payload.get("findings") or []}
    for b in payload.get("blocking_findings") or []:
        if b.get("finding_id") not in finding_ids:
            issues.append(f"invariant: blocking finding {b.get('finding_id')} missing from findings")

    return {
        "valid": not issues,
        "issues": issues,
        "blocking_count": blocking_count,
        "status": status,
        "state_recommendation": rec,
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("check-self", lambda: main(read_stdin_envelope()))
