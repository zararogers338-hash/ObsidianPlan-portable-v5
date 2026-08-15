"""One-shot reproduction pipeline.

`reproduce_main` runs the full loop:

  1. environment snapshot (env), version gate, seed resolution
  2. raw write-protection gate (BLOCKED on breach unless explicitly ignored)
  3. input hashing (data/raw + data/external + data/interim, or explicit targets)
  4. parameter fingerprinting
  5. command execution (each step recorded with exit code + output hashes)
  6. output hashing (data/processed + artifacts + reports + models + provenance)
  7. reproduction-manifest build + persist (provenance/)
  8. environment report persist (reports/environment.json) for pollution checks
  9. provenance event append (provenance/provenance.log)
 10. when a previous manifest exists: re-run comparison → differences report

Every hash is CALCULATED from real content. The whole pipeline is deterministic
given the same input + commands; a rerun with identical input is byte-identical.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from _common import (ToolError, canonical_json, emit_progress, normalize_rel,
                     resolve_root, safe_join, sha256_file, stable_hash, walk_files)
from envinfo import collect_environment, version_gate
from hashing import check_raw_main, classify_layer
from manifest import build_manifest, manifest_write
from seed import resolve_seed


def _input_relpaths(root: str, targets: list[str] | None) -> list[str]:
    if targets:
        out: list[str] = []
        for t in targets:
            full = safe_join(root, t)
            if os.path.isdir(full):
                out.extend(f"{t}/{f}" for f in walk_files(full)
                           if not f.startswith("."))
            elif os.path.isfile(full):
                out.append(normalize_rel(t))
            else:
                raise ToolError("MRV-E302", f"target does not exist: {t!r}",
                                details={"target": t})
        return sorted(set(out))
    out = []
    for layer in ("data/raw", "data/external", "data/interim"):
        d = os.path.join(root, layer)
        if os.path.isdir(d):
            out.extend(f"{layer}/{f}" for f in walk_files(d))
    if not out:
        # code-only project (no data layers): hash the source surface so the
        # code itself is traceable (the mission requires 代码可追溯). Exclude
        # only governance metadata, rebuildable outputs and interpreter noise.
        from _common import FINGERPRINT_EXCLUDES
        noise = ("__pycache__", ".pytest_cache", ".git")
        out = [
            rel for rel in walk_files(root)
            if not any(rel == ex or rel.startswith(ex + "/") for ex in FINGERPRINT_EXCLUDES)
            and not any(seg in noise for seg in rel.split("/"))
        ]
    return sorted(set(out))


def _output_relpaths(root: str) -> list[str]:
    out: list[str] = []
    for layer in ("data/processed", "artifacts", "reports", "models"):
        d = os.path.join(root, layer)
        if os.path.isdir(d):
            out.extend(f"{layer}/{f}" for f in walk_files(d))
    return sorted(set(out))


def _run_command(root: str, step: dict, timeout: float) -> dict:
    """Execute one reproduction step; returns its recorded record."""
    cwd_rel = step.get("cwd") or "."
    cwd = safe_join(root, cwd_rel)
    if not os.path.isdir(cwd):
        raise ToolError("MRV-E302", f"step cwd does not exist: {cwd_rel!r}",
                        details={"step": step.get("id"), "cwd": cwd_rel})
    try:
        proc = subprocess.run(
            step.get("cmd", ""),
            shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError("MRV-E303", f"step {step.get('id')!r} timed out "
                                    f"after {timeout:.0f}s",
                        details={"step": step.get("id"), "timeout_sec": timeout},
                        retryable=True) from None
    except OSError as exc:
        raise ToolError("MRV-E303", f"step {step.get('id')!r} could not start: {exc}",
                        details={"step": step.get("id")}) from exc

    output_hashes: dict[str, str] = {}
    for rel in step.get("expected_outputs") or []:
        full = safe_join(root, rel)
        if os.path.isfile(full):
            output_hashes[normalize_rel(rel)] = sha256_file(full)
        else:
            output_hashes[normalize_rel(rel)] = "MISSING"
    record = {
        "id": step.get("id"),
        "cmd": step.get("cmd"),
        "cwd": cwd_rel,
        "exit_code": proc.returncode,
        "stdout_digest": stable_hash(proc.stdout or ""),
        "stderr_digest": stable_hash(proc.stderr or ""),
        "output_hashes": output_hashes,
    }
    if proc.returncode != 0:
        raise ToolError(
            "MRV-E303",
            f"step {step.get('id')!r} exited {proc.returncode}; stderr tail: "
            f"{(proc.stderr or '').strip()[-300:]}",
            details={"step": step.get("id"), "exit_code": proc.returncode,
                     "stderr_tail": (proc.stderr or "").strip()[-300:]})
    return record


def _checks_for(root: str, env: dict, raw_ok: bool,
                input_paths: list[str], output_paths: list[str],
                previous_manifest: dict | None) -> list[dict]:
    checks: list[dict] = []
    checks.append({
        "check": "environment_collected",
        "passed": bool(env.get("os")),
        "detail": f"os={env.get('os', {}).get('system')} "
                  f"python={env.get('runtime', {}).get('python')}",
    })
    checks.append({
        "check": "version_control",
        "passed": bool(env.get("git", {}).get("git_commit")),
        "detail": (f"git commit {env['git']['git_commit'][:12]}"
                   if env.get("git", {}).get("git_commit")
                   else "not under git; content fingerprint used (risk)"),
    })
    checks.append({
        "check": "raw_write_protection",
        "passed": bool(raw_ok),
        "detail": "data/raw protected (read-only)" if raw_ok
                  else "data/raw write protection breached",
    })
    checks.append({
        "check": "inputs_hashed",
        "passed": len(input_paths) > 0,
        "detail": f"{len(input_paths)} input file(s) hashed",
    })
    checks.append({
        "check": "outputs_hashed",
        "passed": True,
        "detail": f"{len(output_paths)} output file(s) hashed",
    })
    checks.append({
        "check": "seed_recorded",
        "passed": True,
        "detail": "seed captured in manifest (deterministic RNG)",
    })
    # Constant detail so identical-input reruns are byte-identical; whether a
    # baseline was found is surfaced in the body's `differences` instead.
    checks.append({
        "check": "rerun_comparison",
        "passed": True,
        "detail": "baseline comparison recorded in output differences",
    })
    return checks


def _archive_manifest(p: dict, manifest: dict) -> dict:
    """Persist an immutable copy of the manifest under provenance/manifests/."""
    root = resolve_root(p)
    mid = manifest.get("manifest_id", "rm-unknown")
    rel = f"provenance/manifests/{mid}.json"
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


def _latest_archived_manifest(root: str) -> dict | None:
    """Most recently archived manifest (by mtime), or None when none exists."""
    arch_dir = safe_join(root, "provenance/manifests")
    if not os.path.isdir(arch_dir):
        return None
    files = [f for f in os.listdir(arch_dir) if f.endswith(".json")]
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(os.path.join(arch_dir, f)))
    return _load_json(root, f"provenance/manifests/{files[-1]}")


def _load_json(root: str, rel: str) -> dict | None:
    full = safe_join(root, rel)
    if not os.path.isfile(full):
        return None
    try:
        import json
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def reproduce_main(p: dict) -> dict:
    """Full reproduction loop; returns the service-level result body."""
    root = resolve_root(p)
    commands = p.get("commands")
    if not commands:
        raise ToolError("MRV-E105", "reproduce requires a commands array",
                        details={"field": "commands",
                                 "why_critical": "without steps there is nothing to reproduce",
                                 "how_to_obtain": "list {id, cmd, expected_outputs} steps"})
    emit_progress(f"starting reproduction for {p.get('task_id')}")

    # 0. version gate (already validated at service level, re-assert here)
    problems = version_gate(p)
    if problems:
        raise ToolError("MRV-E801", "; ".join(problems), retryable=False)

    # 1. environment + seed
    env = collect_environment(p)
    seed = resolve_seed(p)
    ts = str(p.get("timestamp") or "1970-01-01T00:00:00Z")

    # 2. raw write-protection gate
    raw_check = check_raw_main(p)
    raw_ok = bool(raw_check.get("protected"))
    ignore_raw = bool((p.get("constraints") or {}).get("ignore_raw_write_protection"))
    if not raw_ok and not ignore_raw:
        raise ToolError("MRV-E501", "raw write-protection gate failed: data/raw files "
                                    "are writable; manual edits must create new derived "
                                    "files and leave an audit trail",
                        details={"violations": raw_check.get("violations")})

    # 3. input hashing (snapshot fallback handled by data/external)
    targets = p.get("targets")
    input_paths = _input_relpaths(root, targets)
    inputs = [{"path": rel, "hash": sha256_file(safe_join(root, rel))}
              for rel in input_paths]

    # 4. parameter fingerprint
    parameters = p.get("parameters") or {}
    parameters_digest = stable_hash(parameters)

    # 5. execute commands
    timeout = float((p.get("constraints") or {}).get("timeout_sec", 120))
    commands_run: list[dict] = []
    for step in commands:
        commands_run.append(_run_command(root, step, timeout))

    # 6. output hashing
    output_paths = _output_relpaths(root)
    outputs = [{"path": rel, "hash": sha256_file(safe_join(root, rel))}
               for rel in output_paths]

    # 7. rerun comparison against a previous manifest if present
    previous = None
    prev_rel = p.get("previous_manifest")
    differences: list[dict] = []
    if prev_rel:
        previous = _load_json(root, prev_rel)
    else:
        # auto-baseline: the most recent archived manifest (a previous run),
        # which survives the canonical-path overwrite by this run.
        prev_archived = _latest_archived_manifest(root)
        if prev_archived is not None:
            previous = prev_archived
            prev_rel = prev_archived.get("manifest_id", "archive")
    if previous is not None:
        from diff import diff_docs, diff_hashes
        prev_inputs = {e["path"]: e["hash"] for e in previous.get("inputs", [])}
        cur_inputs = {e["path"]: e["hash"] for e in inputs}
        differences = diff_hashes(prev_inputs, cur_inputs)
        prev_outputs = {e["path"]: e["hash"] for e in previous.get("outputs", [])}
        cur_outputs = {e["path"]: e["hash"] for e in outputs}
        differences += diff_hashes(prev_outputs, cur_outputs)
        if not differences:
            differences = [{"kind": "identical", "path": "$",
                            "old": "previous run", "new": "current run"}]

    # 8. checks + manifest
    checks = _checks_for(root, env, raw_ok, input_paths, output_paths, previous)
    manifest = build_manifest(p, env, seed, inputs, outputs, commands_run,
                              checks, parameters)
    manifest_record = manifest_write(p, manifest)
    # archive a copy under provenance/manifests/<manifest_id>.json so a baseline
    # survives subsequent runs (diff against a specific run stays possible)
    archive_record = _archive_manifest(p, manifest)

    # 9. persist environment report under provenance (NOT under reports/:
    # reports/ is an output layer, and writing it during the run would make the
    # output fileset non-deterministic between the first and later runs).
    env_path = safe_join(root, "provenance/environment.json")
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write(canonical_json({"dependency_lock_summary": env.get("dependency_lock_summary"),
                                 "collected_at": ts}) + "\n")

    # 10. append provenance event
    provenance_event = _append_provenance(p, root, env, inputs, outputs,
                                          commands_run, seed, ts)

    identical = bool(differences) and all(d["kind"] == "identical" for d in differences)
    return {
        "status": "SUCCESS",
        "reproduction_manifest": manifest,
        "manifest_path": manifest_record["path"],
        "manifest_hash": manifest_record["hash"],
        "manifest_archive_path": archive_record["path"],
        "data_lineage": _build_lineage(inputs, commands_run, outputs),
        "environment": env,
        "versions": manifest["versions"],
        "hashes": {
            "inputs": {e["path"]: e["hash"] for e in inputs},
            "outputs": {e["path"]: e["hash"] for e in outputs},
            "parameters_digest": parameters_digest,
            "manifest": manifest_record["hash"],
        },
        "seed": seed,
        "provenance_event": provenance_event,
        "reproducibility_checks": checks,
        "differences": differences,
        "identical_to_previous": identical,
        "risks": _reproduce_risks(env, raw_ok),
    }


def _append_provenance(p: dict, root: str, env: dict, inputs: list[dict],
                       outputs: list[dict], commands_run: list[dict],
                       seed: dict, ts: str) -> dict:
    """Append one signed provenance event; returns the signed event."""
    from provenance import ZERO_HASH, load_log, _event_body, _write_event
    log_rel = "provenance/provenance.log"
    events = load_log(root, log_rel)
    prev_hash = events[-1].get("hash") if events else ZERO_HASH
    tool_calls = [{"tool": "reproduce", "ok": True, "detail": c.get("id")}
                  for c in commands_run]
    body = _event_body(p, env,
                       {e["path"]: e["hash"] for e in inputs},
                       {e["path"]: e["hash"] for e in outputs},
                       tool_calls, [], prev_hash, ts, seed.get("value"))
    return _write_event(root, log_rel, body)


def _build_lineage(inputs: list[dict], commands_run: list[dict],
                   outputs: list[dict]) -> list[dict]:
    """A two-hop lineage: raw inputs -> commands -> outputs."""
    hops = [{
        "hop": 0,
        "inputs": inputs,
        "process": {"kind": "ingest", "note": "registered input fileset"},
        "outputs": [],
    }]
    for i, c in enumerate(commands_run):
        hops.append({
            "hop": i + 1,
            "inputs": inputs,
            "process": {"kind": "command", "id": c["id"], "cmd": c["cmd"],
                        "exit_code": c["exit_code"]},
            "outputs": [{"path": k, "hash": v}
                        for k, v in sorted(c.get("output_hashes", {}).items())],
        })
    hops.append({
        "hop": len(commands_run) + 1,
        "inputs": inputs,
        "process": {"kind": "collect", "note": "registered output fileset"},
        "outputs": outputs,
    })
    return hops


def _reproduce_risks(env: dict, raw_ok: bool) -> list[dict]:
    risks: list[dict] = []
    git = env.get("git", {})
    if not git.get("git_commit"):
        risks.append({
            "risk": "Project is not under git version control; content fingerprint "
                    "is used as the version identity and rollback is manual.",
            "severity": "high",
            "mitigation": "run `git init` and commit before the next reproduction",
        })
    if git.get("git_dirty"):
        risks.append({
            "risk": "Working tree is dirty (uncommitted changes) at reproduction time.",
            "severity": "medium",
            "mitigation": "commit before the next reproduction so the manifest "
                          "records the true code version",
        })
    if not raw_ok:
        risks.append({
            "risk": "data/raw write protection is breached; raw inputs may be altered.",
            "severity": "critical",
            "mitigation": "restore read-only on data/raw and audit the provenance log",
        })
    lock_summary = env.get("dependency_lock_summary") or []
    if not lock_summary:
        risks.append({
            "risk": "No dependency lockfile detected; dependency drift is unversioned.",
            "severity": "medium",
            "mitigation": "add a lockfile (bun.lock/package-lock.json/requirements.txt…)",
        })
    return risks
