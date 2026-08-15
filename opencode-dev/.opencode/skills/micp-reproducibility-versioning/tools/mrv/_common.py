"""Shared utilities for micp-reproducibility-versioning tools.

All tools are pure standard-library Python (>=3.10), offline, and deterministic.
They communicate over stdin/stdout with JSON envelopes:

  success: {"ok": true,  "tool": <name>, "version": <semver>, "result": {...}}
  failure: {"ok": false, "tool": <name>, "version": <semver>,
            "error": {"code": <machine code>, "message": <human readable>,
                      "retryable": <bool>, "details": {...}}}

Exit codes: 0 success; 2 input/validation problem; 3 graph/contract problem;
4 internal error. Numbers are rejected when non-finite; unknown JSON fields are
rejected where schemas say `additionalProperties: false`.

Determinism rule: every timestamp that appears in tool output is derived from
the *input* `timestamp` field, never from the wall clock, so two runs on
identical input produce byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from typing import Any

TOOLSET_VERSION = "1.0.0"


class ToolError(Exception):
    """An expected, classifiable failure. Carries a machine-readable code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: dict[str, Any] | None = None, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def read_json_stdin() -> Any:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ToolError("E_INPUT_EMPTY", "stdin was empty; expected a JSON document")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(
            "E_INPUT_INVALID_JSON",
            f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
            details={"line": exc.lineno, "column": exc.colno},
        )


def _reject_non_finite(node: Any, path: str = "$") -> None:
    if isinstance(node, float) and not math.isfinite(node):
        raise ToolError("E_NUMERIC_NON_FINITE", f"non-finite number at {path}",
                        details={"path": path})
    if isinstance(node, dict):
        for k, v in node.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _reject_non_finite(v, f"{path}[{i}]")


def reject_non_finite(doc: Any) -> Any:
    _reject_non_finite(doc)
    return doc


def envelope_ok(tool: str, result: dict[str, Any]) -> str:
    return json.dumps({"ok": True, "tool": tool, "version": TOOLSET_VERSION,
                       "result": result}, ensure_ascii=False, indent=2, sort_keys=True)


def envelope_err(tool: str, err: ToolError) -> str:
    return json.dumps({"ok": False, "tool": tool, "version": TOOLSET_VERSION,
                       "error": {"code": err.code, "message": err.message,
                                 "retryable": err.retryable,
                                 "details": err.details}},
                      ensure_ascii=False, indent=2, sort_keys=True)


def run_tool(tool: str, fn) -> None:
    """Entry-point wrapper: fn(stdin_json) -> result dict. Handles envelopes."""
    try:
        payload = read_json_stdin()
        reject_non_finite(payload)
        result = fn(payload)
        sys.stdout.write(envelope_ok(tool, result) + "\n")
        sys.exit(0)
    except ToolError as err:
        sys.stdout.write(envelope_err(tool, err) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - last-resort guard, must not leak stack-only failure
        err = ToolError("E_INTERNAL", f"unexpected internal error: {type(exc).__name__}: {exc}",
                        retryable=True, exit_code=4)
        sys.stdout.write(envelope_err(tool, err) + "\n")
        sys.exit(4)


def emit_progress(message: str) -> None:
    """Progress lines go to stderr so stdout stays machine-parseable."""
    sys.stderr.write(f"[micp-reproducibility-versioning] {message}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Type coercion guards
# ---------------------------------------------------------------------------

def require(cond: bool, code: str, message: str, **details: Any) -> None:
    if not cond:
        raise ToolError(code, message, details=details or None)


def as_str(value: Any, path: str, *, min_len: int = 0, max_len: int | None = None) -> str:
    require(isinstance(value, str), "E_TYPE", f"{path} must be a string", path=path, got=type(value).__name__)
    require(len(value) >= min_len, "E_RANGE", f"{path} must be at least {min_len} chars", path=path)
    if max_len is not None:
        require(len(value) <= max_len, "E_RANGE", f"{path} must be at most {max_len} chars", path=path)
    return value


def as_int(value: Any, path: str, *, min_v: int | None = None, max_v: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("E_TYPE", f"{path} must be an integer", details={"path": path})
    if min_v is not None and value < min_v:
        raise ToolError("E_RANGE", f"{path} must be >= {min_v}", details={"path": path})
    if max_v is not None and value > max_v:
        raise ToolError("E_RANGE", f"{path} must be <= {max_v}", details={"path": path})
    return value


def as_list(value: Any, path: str, *, min_len: int = 0, max_len: int | None = None) -> list:
    if not isinstance(value, list):
        raise ToolError("E_TYPE", f"{path} must be an array", details={"path": path})
    if len(value) < min_len:
        raise ToolError("E_RANGE", f"{path} must have at least {min_len} items", details={"path": path})
    if max_len is not None and len(value) > max_len:
        raise ToolError("E_RANGE", f"{path} must have at most {max_len} items", details={"path": path})
    return value


def as_dict(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ToolError("E_TYPE", f"{path} must be an object", details={"path": path})
    return value


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Canonical JSON + hashing (the evidence primitives)
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    """Deterministic serialization: sorted keys, no insignificant whitespace."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def stable_hash(obj: Any) -> str:
    """Hash of a canonical JSON document — the identity of any structured value."""
    return sha256_hex(canonical_json(obj))


def sha256_file(path: str) -> str:
    """SHA-256 of file content. The single source of truth for content integrity."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Filesystem walk / fingerprints / path safety
# ---------------------------------------------------------------------------

def normalize_rel(path: str) -> str:
    return path.replace("\\", "/")


def walk_files(root: str, *, skip_hidden: bool = True) -> list[str]:
    """All regular files under root, as sorted forward-slash relative paths."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            filenames = [f for f in filenames if not f.startswith(".")]
        dirnames.sort()
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            if os.path.isfile(full):
                out.append(normalize_rel(os.path.relpath(full, root)))
    return sorted(out)


def dir_fingerprint(root: str, relpaths: list[str] | None = None,
                    exclude: tuple[str, ...] = ()) -> str:
    """Deterministic content fingerprint of a directory tree.

    Hash over "relpath NUL sha256" lines. Used as the git fallback so a tree
    without version control still gets a stable, content-derived identity.

    `exclude` lists top-level relative prefixes whose contents are governance
    metadata (provenance/, reports/, lockfiles/...) and must NOT feed the
    identity — otherwise every reproduction run (which writes those files)
    would change the project's fingerprint.
    """
    if relpaths is None:
        relpaths = [
            rel for rel in walk_files(root)
            if not any(rel == ex or rel.startswith(ex + "/") for ex in exclude)
        ]
    lines = [f"{rel}\x00{sha256_file(os.path.join(root, rel))}" for rel in relpaths]
    return sha256_hex("\n".join(lines))


def safe_join(root: str, rel: str) -> str:
    """Join root + relative path, refusing escapes outside root."""
    rp = os.path.realpath(root)
    joined = os.path.realpath(os.path.join(rp, rel))
    if os.path.commonpath([rp, joined]) != rp:
        raise ToolError("MRV-E302", f"path escapes the governance root: {rel!r}",
                        details={"root": rp, "path": joined})
    return joined


# Top-level directories that must NOT feed a project's git-fallback
# fingerprint: governance metadata (written by every run) and rebuildable
# outputs (data/processed, artifacts, models… are produced from code). Only
# the immutable-source surface — data/raw, data/external, data/interim inputs,
# evidence, experiments and code — defines the project identity.
GOVERNANCE_METADATA_DIRS = ("provenance", "reports", "lockfiles")
REBUILDABLE_OUTPUT_DIRS = ("data/processed", "data/interim", "artifacts",
                           "models", "failures")
FINGERPRINT_EXCLUDES = GOVERNANCE_METADATA_DIRS + REBUILDABLE_OUTPUT_DIRS


def resolve_root(p: dict) -> str:
    root = p.get("root") or os.getcwd()
    if not os.path.isdir(root):
        raise ToolError("MRV-E104", f"root is not a readable directory: {root!r}",
                        details={"root": root})
    return os.path.realpath(root)
