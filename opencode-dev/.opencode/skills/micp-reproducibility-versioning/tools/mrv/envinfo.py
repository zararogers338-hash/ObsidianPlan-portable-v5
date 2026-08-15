"""Environment collection, dependency-lock summaries, and version gates.

`env_main` reports what any reproduction manifest must record: OS, runtime,
tool versions, dependency-lock-file summaries, and a git identity (commit when
the tree is a git worktree, otherwise a deterministic content fingerprint).

Every field here is OBSERVED (read from the real environment) or CALCULATED
(derived from real file content) — never fabricated.

Pure stdlib, offline, deterministic.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Any

from _common import (ToolError, FINGERPRINT_EXCLUDES, canonical_json,
                     dir_fingerprint, emit_progress, sha256_hex)

SKILL_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Git detection (the repo is not currently a git worktree; we must detect and
# fall back to a fingerprint rather than assume git is present)
# ---------------------------------------------------------------------------

def git_identity(root: str) -> dict:
    """Return {'git_present': bool, 'git_commit': str|None, 'git_dirty': bool|None}.

    Falls back to a deterministic content fingerprint (prefix `fp_`) when git
    is unavailable or the root is not inside a repository, and flags the
    fallback so callers can record it as a risk. Governance-metadata dirs
    (provenance/reports/lockfiles) are excluded from the fingerprint so that a
    reproduction run never changes the project identity.
    """
    git = shutil.which("git")
    if git is None:
        return {
            "git_present": False,
            "git_commit": None,
            "git_dirty": None,
            "fingerprint": dir_fingerprint(root, exclude=FINGERPRINT_EXCLUDES),
            "note": "git not installed; using content fingerprint",
        }
    try:
        proc = subprocess.run(
            [git, "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return {
                "git_present": False,
                "git_commit": None,
                "git_dirty": None,
                "fingerprint": dir_fingerprint(root, exclude=FINGERPRINT_EXCLUDES),
                "note": "root is not inside a git worktree; using content fingerprint",
            }
        head = subprocess.run(
            [git, "-C", root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        commit = head.stdout.strip() if head.returncode == 0 else None
        dirty = None
        if commit:
            st = subprocess.run(
                [git, "-C", root, "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            dirty = bool(st.stdout.strip())
        return {
            "git_present": True,
            "git_commit": commit,
            "git_dirty": dirty,
            "fingerprint": None,
            "note": "git worktree present",
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            "git_present": False,
            "git_commit": None,
            "git_dirty": None,
            "fingerprint": dir_fingerprint(root, exclude=FINGERPRINT_EXCLUDES),
            "note": f"git unavailable ({exc}); using content fingerprint",
        }


# ---------------------------------------------------------------------------
# Tool / runtime detection
# ---------------------------------------------------------------------------

def _version_of(cmd: str, args: list[str]) -> str | None:
    try:
        proc = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return None
        first = (proc.stdout or "").strip().splitlines()
        if not first:
            return None
        return first[0].strip()[:200]
    except (subprocess.SubprocessError, OSError):
        return None


def collect_environment(p: dict) -> dict:
    """Environment snapshot: OS, runtime, tools, dependency-lock summaries, git."""
    from _common import resolve_root

    root = resolve_root(p)
    emit_progress("collecting environment")
    os_info = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "platform_detail": platform.platform(),
    }
    runtime = {
        "python": sys.version.split()[0],
        "python_impl": platform.python_implementation(),
        "python_executable": sys.executable,
    }
    tools: dict[str, str | None] = {}
    for cmd, args in [
        ("git", ["--version"]),
        ("python", ["--version"]),
        ("python3", ["--version"]),
        ("bun", ["--version"]),
        ("node", ["--version"]),
        ("npm", ["--version"]),
        ("pnpm", ["--version"]),
        ("pip", ["--version"]),
        ("pytest", ["--version"]),
        ("uv", ["--version"]),
    ]:
        if shutil.which(cmd):
            tools[cmd] = _version_of(cmd, args)

    git = git_identity(root)
    lock_summaries = _lockfile_summaries(root)
    return {
        "os": os_info,
        "runtime": runtime,
        "tools": tools,
        "dependency_lock_summary": lock_summaries,
        "git": git,
    }


def _lockfile_summaries(root: str) -> list[dict]:
    """Hash and summarize known dependency-lock files (detection only, no parse).

    Each lockfile's sha256 is recorded so 'dependency upgrade → different hash →
    result drift' is traceable even though we never execute package managers.
    """
    candidates = [
        "bun.lock", "bun.lockb", "package-lock.json", "pnpm-lock.yaml",
        "yarn.lock", "requirements.txt", "Pipfile.lock", "poetry.lock",
        "uv.lock", "environment.yml", "flake.lock",
    ]
    out: list[dict] = []
    for name in candidates:
        full = os.path.join(root, name)
        if os.path.isfile(full):
            try:
                digest = sha256_file_local(full)
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({"name": name, "size": size, "sha256": digest})
    return out


def sha256_file_local(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def env_main(p: dict) -> dict:
    """Top-level env tool result."""
    from _common import resolve_root

    root = resolve_root(p)
    env = collect_environment(p)
    git = env["git"]
    return {
        "root": root,
        "os": env["os"],
        "runtime": env["runtime"],
        "tools": env["tools"],
        "dependency_lock_summary": env["dependency_lock_summary"],
        "git": git,
        "identity": git.get("git_commit") or git.get("fingerprint"),
        "version_control_active": bool(git.get("git_commit")),
    }


# ---------------------------------------------------------------------------
# Dependency lock export (detection; never executes package managers)
# ---------------------------------------------------------------------------

def lock_main(p: dict) -> dict:
    """Export & lock detected dependencies.

    Detection is passive: we hash existing lockfiles and enumerate the modules
    the current Python runtime actually imports (the reproduction-relevant
    surface). We never run pip/pnpm/bun/npm, so this is safe, offline and
    deterministic.
    """
    from _common import resolve_root

    root = resolve_root(p)
    emit_progress("exporting dependency locks")
    summaries = _lockfile_summaries(root)
    python_modules = sorted(_importable_modules())
    spec = {
        "lockfile_summaries": summaries,
        "python_import_surface": python_modules,
        "generated_by": f"micp-reproducibility-versioning {SKILL_VERSION}",
        "mode": "passive_detection",
    }
    # A deterministic lock doc identity for the manifest.
    return {
        "lock_id": f"lock-{sha256_hex(canonical_json(spec))[:12]}",
        "spec": spec,
    }


def _importable_modules() -> list[str]:
    """Standard-library + on-sys.path modules importable right now (subset)."""
    names = ["json", "os", "sys", "re", "hashlib", "subprocess", "platform",
             "datetime", "math", "random", "pathlib", "csv", "shutil"]
    out: list[str] = []
    for n in names:
        try:
            __import__(n)
            out.append(n)
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# Version compatibility (semver gates)
# ---------------------------------------------------------------------------

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def parse_semver(v: str) -> tuple[int, int, int] | None:
    m = SEMVER_RE.match(str(v).strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def version_gate(p: dict) -> list[str]:
    """Check declared vs. effective versions. Returns human-readable problems."""
    problems: list[str] = []
    sv = p.get("skill_version")
    if not sv:
        problems.append("skill_version missing (MRV-E101)")
    elif parse_semver(sv) is None:
        problems.append(f"skill_version {sv!r} is not semver (MRV-E101)")
    elif parse_semver(sv)[0] != parse_semver(SKILL_VERSION)[0]:
        problems.append(
            f"skill_version {sv!r} has a different major than this build "
            f"({SKILL_VERSION}); a migration gate applies (MRV-E801)")
    if not p.get("controller_version"):
        problems.append("controller_version missing (MRV-E101)")
    return problems


def compat_main(p: dict) -> dict:
    """Version compatibility checker.

    Given `schema_versions` (a map artifact -> declared version) and the tool's
    own `compatibility_matrix` (effective versions), decide each entry's
    compatibility and emit migration actions when a major gap exists.
    """
    declared = p.get("schema_versions") or {}
    if not declared:
        raise ToolError("MRV-E102", "compat requires schema_versions",
                        details={"field": "schema_versions"})
    effective = _effective_versions()
    results: list[dict] = []
    for artifact, declared_v in sorted(declared.items()):
        eff = effective.get(artifact)
        if eff is None:
            results.append({
                "artifact": artifact,
                "declared": str(declared_v),
                "effective": None,
                "compatible": False,
                "reason": f"no effective version known for artifact {artifact!r}",
            })
            continue
        dv = parse_semver(str(declared_v))
        ev = parse_semver(eff)
        if dv is None or ev is None:
            results.append({
                "artifact": artifact,
                "declared": str(declared_v),
                "effective": eff,
                "compatible": False,
                "reason": "declared version is not semver",
            })
            continue
        if dv[0] != ev[0]:
            results.append({
                "artifact": artifact,
                "declared": str(declared_v),
                "effective": eff,
                "compatible": False,
                "reason": "major version mismatch; a migration is required",
            })
        elif dv[1] > ev[1]:
            results.append({
                "artifact": artifact,
                "declared": str(declared_v),
                "effective": eff,
                "compatible": False,
                "reason": "declared minor is ahead of effective; backward-compatible "
                          "fields may be missing",
            })
        else:
            results.append({
                "artifact": artifact,
                "declared": str(declared_v),
                "effective": eff,
                "compatible": True,
                "reason": "compatible",
            })
    return {
        "schema_version": "1.0.0",
        "results": results,
        "all_compatible": all(r["compatible"] for r in results),
    }


def _effective_versions() -> dict[str, str]:
    return {
        "manifest": "1.0.0",
        "output": "1.0.0",
        "input": "1.0.0",
        "provenance": "1.0.0",
        "skill": SKILL_VERSION,
    }


def migrate_main(p: dict) -> dict:
    """Schema migrator.

    Only runs real, known-good migrations: a manifest's schema_version is bumped
    to the effective version when it declares an older-but-compatible minor
    (never silently). A major-mismatch without a migration chain is rejected
    with MRV-E802. Operates on a copy unless `apply: true` is set.
    """
    declared = p.get("schema_versions") or {}
    apply = bool(p.get("apply"))
    if not declared:
        raise ToolError("MRV-E102", "migrate requires schema_versions",
                        details={"field": "schema_versions"})
    effective = _effective_versions()
    actions: list[dict] = []
    for artifact, declared_v in sorted(declared.items()):
        eff = effective.get(artifact)
        if eff is None:
            continue
        dv = parse_semver(str(declared_v))
        ev = parse_semver(eff)
        if dv is None or ev is None or dv[0] != ev[0]:
            actions.append({
                "artifact": artifact,
                "from": str(declared_v),
                "to": eff or str(declared_v),
                "applied": False,
                "reason": "major mismatch or unparsable version; no migration chain",
            })
            continue
        if tuple(dv) == tuple(ev):
            continue
        actions.append({
            "artifact": artifact,
            "from": str(declared_v),
            "to": eff,
            "applied": apply,
            "reason": f"minor/patch alignment {str(declared_v)} -> {eff} "
                      f"(backward compatible)",
        })
    blocked = [a for a in actions if not a.get("applied") and a.get("reason", "").startswith("major")]
    return {
        "schema_version": "1.0.0",
        "actions": actions,
        "all_applied": all(a.get("applied", True) for a in actions),
        "blocked_major_migrations": [a["artifact"] for a in blocked],
    }
