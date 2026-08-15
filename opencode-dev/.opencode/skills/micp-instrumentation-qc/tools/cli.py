#!/usr/bin/env python3
"""micp-instrumentation-qc: CLI entry point.

Single entry point for all tools. Reads a JSON envelope from stdin, dispatches to
the requested subcommand, writes a JSON envelope to stdout.

Usage (via bun, so import paths resolve):
    cat input.json | bunx python3 tools/cli.py <subcommand>

Subcommands:
    qc             full QC pipeline (see qc_pipeline.py)
    calibration    calibration curve + LOD/LOQ + expanded uncertainty
    control        Shewhart control chart + drift/over-range/saturation/baseline
    sample-chain   sample chain + barcode + duplicate-ID + timestamp checks
    integrity      raw/derived hashing + audit-log append + chain verification
    adapters       instrument export parsing + unit normalization
    check-self     self-check: tool importability + error-code table integrity

Exit codes: 0 success, 3 input/validation error, 4 internal/self-check error.
"""

from __future__ import annotations

import json
import sys
from typing import Any

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])

from _common import ERROR_CODES, error, emit, read_input  # noqa: E402

try:
    import calibration
    import control_chart
    import sample_chain
    import integrity
    import adapters
    import qc_pipeline
    _IMPORTS_OK = True
    _IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - defensive
    _IMPORTS_OK = False
    _IMPORT_ERROR = repr(exc)


def _dispatch(subcommand: str, data: dict[str, Any]) -> dict[str, Any]:
    if subcommand == "calibration":
        return {"result": calibration.compute(data)}
    if subcommand == "control":
        return {"result": control_chart.check_measurements(data)}
    if subcommand == "sample-chain":
        return {"result": sample_chain.check_samples(data)}
    if subcommand == "integrity":
        return {"result": integrity.run(data)}
    if subcommand == "adapters":
        return {"result": adapters.run(data)}
    if subcommand == "qc":
        return qc_pipeline.run(data)
    if subcommand == "check-self":
        return {
            "imports_ok": _IMPORTS_OK,
            "import_error": _IMPORT_ERROR,
            "error_codes": list(ERROR_CODES.keys()),
            "modules": ["calibration", "control_chart", "sample_chain", "integrity", "adapters", "qc_pipeline"],
        }
    raise ValueError(f"MICQ-E1003: unknown subcommand '{subcommand}'")


def main() -> int:
    if len(sys.argv) < 2:
        emit({"ok": False, "errors": [error("MICQ-E1001", {"reason": "no subcommand provided"})]}, exit_code=3)
        return 3

    subcommand = sys.argv[1]
    if subcommand == "check-self":
        try:
            from _common import ERROR_CODES  # noqa: F401

            result = {"result": {
                "imports_ok": _IMPORTS_OK,
                "import_error": _IMPORT_ERROR,
                "error_codes": list(ERROR_CODES.keys()),
                "modules": ["calibration", "control_chart", "sample_chain", "integrity", "adapters", "qc_pipeline"],
            }}
            emit(result, exit_code=0 if _IMPORTS_OK else 4)
            return 0 if _IMPORTS_OK else 4
        except Exception as exc:  # pragma: no cover
            emit({"ok": False, "errors": [error("MICQ-E1011", {"reason": repr(exc)})]}, exit_code=4)
            return 4

    try:
        data = read_input()
    except Exception as exc:
        emit({"ok": False, "errors": [error("MICQ-E1001", {"reason": repr(exc)})]}, exit_code=3)
        return 3

    try:
        result = _dispatch(subcommand, data)
        # Validation: result must be JSON-serializable.
        json.dumps(result, ensure_ascii=False)
        emit(result, exit_code=0)
        return 0
    except ValueError as exc:
        # Input/validation errors -> human-readable + machine-parseable.
        message = str(exc)
        code = "MICQ-E1001"
        for c in ("MICQ-E1001", "MICQ-E1002", "MICQ-E1003", "MICQ-E1004", "MICQ-E1009", "MICQ-E1010"):
            if message.startswith(c):
                code = c
                message = message[len(c):].lstrip(": ")
                break
        emit({"ok": False, "errors": [error(code, {"reason": message})]}, exit_code=3)
        return 3
    except Exception as exc:  # pragma: no cover
        emit({"ok": False, "errors": [error("MICQ-E1011", {"reason": repr(exc)})]}, exit_code=4)
        return 4


if __name__ == "__main__":
    sys.exit(main())
