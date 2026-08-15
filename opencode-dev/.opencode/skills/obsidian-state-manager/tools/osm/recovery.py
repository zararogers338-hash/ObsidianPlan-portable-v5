"""Crash / context-truncation recovery (tool 3 of spec §五, §四.5).

Recovery model:
  - The event log is authoritative. A snapshot is a cache.
  - On resume we rebuild from the log, compare against the snapshot, and
    classify: CLEAN (snapshot matches), SNAPSHOT_STALE (log advanced since
    snapshot — normal after a crash between append and snapshot write),
    SNAPSHOT_CORRUPT (OSM-E302), LOG_CORRUPT (OSM-E301, needs human).
  - Task checkpoints let a resumed run skip work that completed unchanged:
    resume_plan() returns, per task, the checkpoint's completed_work keyed by
    content hash so callers re-execute only what changed (acceptance §九.3).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import OsmError, OsmErrorCode
from .store import EventStore, Projection


def work_item_key(item: dict[str, Any]) -> str:
    """Stable content key for a completed-work item; if the inputs describing
    the work are byte-identical, the work must not be re-executed."""
    blob = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def recover(store: EventStore, project_id: str) -> dict[str, Any]:
    """Rebuild from the log and classify recovery status. Raises only on
    LOG_CORRUPT — everything else is reported, not thrown, because recovery's
    job is to get the controller moving again."""
    proj = store.rebuild(project_id)  # raises OSM-E301 if log is corrupt

    status = "CLEAN"
    snapshot_revision: int | None = None
    snapshot_state: str | None = None
    try:
        snap = store.read_snapshot(project_id)
        snapshot_revision = int(snap.get("revision", -1))
        snapshot_state = snap.get("state")
        if snapshot_revision != proj.revision or snapshot_state != proj.state.value:
            status = "SNAPSHOT_STALE"
    except OsmError as exc:
        if exc.code is OsmErrorCode.SNAPSHOT_CORRUPT:
            status = "SNAPSHOT_MISSING_OR_CORRUPT"
        else:
            raise

    checkpoints_by_task: dict[str, dict[str, Any]] = {}
    for c in proj.checkpoints:
        # Later checkpoints supersede earlier ones for the same task_id.
        checkpoints_by_task[c["task_id"]] = c

    return {
        "status": status,
        "project_id": project_id,
        "current_state": proj.state.value,
        "head_revision": proj.revision,
        "snapshot_revision": snapshot_revision,
        "snapshot_state": snapshot_state,
        "tasks": {
            task_id: {
                "state": c["state"],
                "completed_work_keys": [work_item_key(w) for w in c.get("completed_work", [])],
                "completed_work": c.get("completed_work", []),
                "pending_work": c.get("pending_work", []),
                "checkpoint_revision": c["revision"],
            }
            for task_id, c in checkpoints_by_task.items()
        },
        "guidance": _guidance_for(proj.state.value),
    }


def _guidance_for(state: str) -> str:
    return {
        "OPEN": "Resume by locking scope (mission-lock skill), then transition to SCOPED.",
        "SCOPED": "Resume by dispatching evidence gathering.",
        "EVIDENCE_GATHERING": "Re-issue only scouting tasks whose outputs are absent from evidence[].",
        "HYPOTHESIS_BUILDING": "Existing hypotheses are intact; add only missing ones.",
        "DESIGNING": "Checkpoint required before AWAITING_DATA; do not redesign completed, unchanged steps.",
        "AWAITING_DATA": "Safe to wait; do not re-run experiments already registered as evidence.",
        "ANALYZING": "Re-run only analyses whose inputs changed since the last checkpoint.",
        "UNDER_REVIEW": "Await review verdict; no compute needed.",
        "VALIDATED": "Knowledge is validated; only watcher-flagged staleness can move it back.",
        "REJECTED": "Terminal; reopen only with human approval.",
        "DEPLOYABLE": "Terminal and irreversible.",
    }.get(state, "Rebuild projection and follow the transition table.")


def resume_plan(store: EventStore, project_id: str, task_id: str,
                current_work: list[dict[str, Any]]) -> dict[str, Any]:
    """Given the work a caller *would* do, return what must actually be done.

    current_work items are matched by content key against the task's latest
    checkpoint; unchanged items are reported as skippable (already_done),
    changed/new ones as to_run. This is the enforcement of §九.3.
    """
    rec = recover(store, project_id)
    task = rec["tasks"].get(task_id)
    already_keys = set(task["completed_work_keys"]) if task else set()

    to_run, already_done = [], []
    for item in current_work:
        key = work_item_key(item)
        entry = {"key": key, "work": item}
        (already_done if key in already_keys else to_run).append(entry)

    return {
        "project_id": project_id,
        "task_id": task_id,
        "current_state": rec["current_state"],
        "recovery_status": rec["status"],
        "to_run": to_run,
        "already_done": already_done,
        "skipped_count": len(already_done),
        "note": "Items in already_done MUST NOT be re-executed unless their inputs changed "
                "(in which case their key would differ and they would appear in to_run).",
    }
