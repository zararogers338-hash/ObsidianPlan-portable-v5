"""Reproduction Manifest builder.

A reproduction manifest is the single self-contained record of one run:
versions (git commit, skill/controller/constitution/schema/model/prompt/data),
environment, seeds, parameters, commands, input hashes, output hashes and
reproducibility checks. It is the artifact a re-run is compared against.

Builder is deterministic: every field is either OBSERVED (read from the real
environment), CALCULATED (from real file content or command output), or
REPORTED (carried verbatim from the input — flagged as such).
"""

from __future__ import annotations

import os
from typing import Any

from _common import (ToolError, canonical_json, emit_progress, normalize_rel,
                     resolve_root, safe_join, sha256_file, stable_hash, walk_files)


def _hash_paths(root: str, relpaths: list[str]) -> list[dict]:
    entries: list[dict] = []
    for rel in sorted(set(relpaths)):
        full = safe_join(root, rel)
        if not os.path.isfile(full):
            raise ToolError("MRV-E302", f"expected input file missing: {rel!r}",
                            details={"path": rel})
        entries.append({"path": rel, "hash": sha256_file(full)})
    return entries


def build_manifest(p: dict, env: dict, seed: dict, inputs: list[dict],
                   outputs: list[dict], commands_run: list[dict],
                   checks: list[dict], parameters: dict | None = None) -> dict:
    """Assemble a reproduction manifest dict (validates against its schema)."""
    root = resolve_root(p)
    ts = str(p.get("timestamp") or "1970-01-01T00:00:00Z")
    git = env.get("git", {})
    versions = {
        "git_commit": git.get("git_commit") or git.get("fingerprint"),
        "git_active": bool(git.get("git_commit")),
        "skill": "micp-reproducibility-versioning",
        "skill_version": "1.0.0",
        "controller_version": p.get("controller_version"),
        "constitution": "panshi-constitution",
        "constitution_version": (p.get("versions") or {}).get("constitution", "1.0.0"),
        "schema": {
            "input": "1.0.0",
            "output": "1.0.0",
            "reproduction_manifest": "1.0.0",
            "provenance_event": "1.0.0",
        },
        "model": (p.get("versions") or {}).get("model"),
        "prompt": (p.get("versions") or {}).get("prompt"),
        "data": (p.get("versions") or {}).get("data"),
        "dependency_lock": [l.get("name") for l in env.get("dependency_lock_summary", [])],
    }
    parameters = parameters or {}
    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": f"rm-{stable_hash({'t': ts, 'p': p.get('project_id'),
                                          's': seed.get('value'),
                                          'params': stable_hash(parameters)})[:16]}",
        "created_at": ts,
        "project_id": p.get("project_id"),
        "task_id": p.get("task_id"),
        "versions": versions,
        "environment": {
            "os": env.get("os"),
            "runtime": env.get("runtime"),
            "tools": env.get("tools"),
            "dependency_lock_summary": env.get("dependency_lock_summary"),
            "git": git,
        },
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters or {},
        "seed": {
            "value": seed.get("value"),
            "policy": seed.get("policy"),
        },
        "commands": commands_run,
        "checks": checks,
    }
    return manifest


def manifest_write(p: dict, manifest: dict, rel: str = "provenance/reproduction-manifest.json") -> dict:
    """Write a reproduction manifest under provenance/ (append-safe, fsync)."""
    root = resolve_root(p)
    full = safe_join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(canonical_json(manifest) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    return {"path": normalize_rel(rel), "hash": sha256_file(full)}
