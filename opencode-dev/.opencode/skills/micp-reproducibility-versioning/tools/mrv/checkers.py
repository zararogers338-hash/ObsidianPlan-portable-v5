"""Artifact-pollution detector and raw-data write-protection verifier.

`check-pollution` verifies the three guardrails that keep a reproduction honest:
  1. provenance hash chain is intact (no tampered/deleted events);
  2. lockfile hashes match the environment report (a dependency upgrade changes
     the recorded lock hash → drift is visible);
  3. manifest hashes still match the files on disk (no manual overwrite that
     slipped past provenance).

`check-raw` verifies the data/raw write-protection gate (MRV-E501) — see
hashing.py for the layer classification used here.
"""

from __future__ import annotations

import json
import os
from typing import Any

from _common import (ToolError, emit_progress, normalize_rel, resolve_root,
                     safe_join, sha256_file)
from provenance import load_log, verify_chain


def pollution_main(p: dict) -> dict:
    """Pollution detection across provenance chain, lockfiles, and manifests."""
    root = resolve_root(p)
    emit_progress("checking artifact pollution")

    checks: list[dict] = []
    findings: list[dict] = []

    # 1. provenance chain
    log_rel = "provenance/provenance.log"
    events: list[dict] = []
    if os.path.isfile(safe_join(root, log_rel)):
        try:
            events = load_log(root, log_rel)
            violations = verify_chain(events)
        except ToolError as exc:
            violations = [exc.message]
        if violations:
            for v in violations:
                findings.append({"kind": "provenance_tamper", "detail": v})
            checks.append({"check": "provenance_chain", "passed": False,
                           "detail": f"{len(violations)} violation(s)"})
        else:
            checks.append({"check": "provenance_chain", "passed": True,
                           "detail": f"{len(events)} event(s) intact"})
    else:
        checks.append({"check": "provenance_chain", "passed": True,
                       "detail": "no provenance log (nothing to tamper)"})

    # 2. lockfile drift vs recorded environment report
    env_report = _read_json_if(root, "provenance/environment.json")
    if env_report:
        recorded = {
            e["name"]: e["sha256"]
            for e in (env_report.get("dependency_lock_summary") or [])
        }
        current = _current_lock_hashes(root)
        drift = [n for n in recorded if n in current and current[n] != recorded[n]]
        if drift:
            for name in drift:
                findings.append({
                    "kind": "dependency_drift",
                    "detail": f"lockfile {name} hash changed",
                })
            checks.append({"check": "dependency_lock", "passed": False,
                           "detail": f"{len(drift)} lockfile(s) drifted"})
        else:
            checks.append({"check": "dependency_lock", "passed": True,
                           "detail": "no lockfile drift"})

    # 3. manifest hashes vs live tree
    manifest = _read_json_if(root, "provenance/reproduction-manifest.json")
    if manifest:
        mis = _manifest_mismatches(root, manifest)
        if mis:
            for path, old, new in mis:
                findings.append({
                    "kind": "manifest_mismatch",
                    "detail": f"{path}: recorded {old[:12]}… != {new[:12]}…",
                })
            checks.append({"check": "manifest_integrity", "passed": False,
                           "detail": f"{len(mis)} recorded file(s) differ from disk"})
        else:
            checks.append({"check": "manifest_integrity", "passed": True,
                           "detail": "manifest matches disk"})

    polluted = len(findings) > 0
    return {
        "polluted": polluted,
        "findings": findings,
        "checks": checks,
        "verdict": "clean" if not polluted else "pollution_detected",
    }


def _read_json_if(root: str, rel: str) -> dict | None:
    full = safe_join(root, rel)
    if not os.path.isfile(full):
        return None
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _current_lock_hashes(root: str) -> dict[str, str]:
    candidates = [
        "bun.lock", "bun.lockb", "package-lock.json", "pnpm-lock.yaml",
        "yarn.lock", "requirements.txt", "Pipfile.lock", "poetry.lock",
        "uv.lock", "environment.yml", "flake.lock",
    ]
    out: dict[str, str] = {}
    for name in candidates:
        full = os.path.join(root, name)
        if os.path.isfile(full):
            try:
                out[name] = sha256_file(full)
            except OSError:
                continue
    return out


def _manifest_mismatches(root: str, manifest: dict) -> list[tuple[str, str, str]]:
    """[(path, recorded_hash, current_hash)] for manifest entries vs disk.

    Both the input and output filesets are guarded — a tampered derived file is
    just as much pollution as a tampered raw file. A recorded file that has
    disappeared is reported with current_hash "MISSING" so a deletion is
    surfaced, not silently ignored.
    """
    out: list[tuple[str, str, str]] = []
    entries = list(manifest.get("inputs") or []) + list(manifest.get("outputs") or [])
    if not entries:
        entries = manifest.get("entries") or []
    seen: set[str] = set()
    for e in entries:
        rel = e.get("path")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        recorded = e.get("hash") or e.get("sha256")
        full = safe_join(root, rel)
        if not os.path.isfile(full):
            if recorded:
                out.append((rel, recorded, "MISSING"))
            continue
        try:
            cur = sha256_file(full)
        except OSError:
            continue
        if recorded and cur != recorded:
            out.append((rel, recorded, cur))
    return out
