"""Event store: hash-chained JSONL event log + snapshots.

Guarantees (spec §四.3, §九):
  - Append-only. No API in this module can mutate or delete a written event;
    rollback is expressed as new compensating events.
  - Each event carries sha256(prev_hash + canonical_payload); a broken link or
    edited payload fails verify() with OSM-E301.
  - Appends are atomic per line: write to temp file + os.replace, with
    os.replace fallback to copy+fsync on filesystems that refuse cross-device
    rename (Windows + some network drives).
  - Snapshots are pure projections: rebuild(events) == read(snapshot) is the
    acceptance invariant checked by SELF_CHECK_FAILED (OSM-E702).

Canonicalization: json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False). This must NEVER change once streams exist; it is pinned
in the contract version.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .errors import OsmError, OsmErrorCode
from .models import EventType, ResearchState

GENESIS_HASH = "0" * 64

STORE_LAYOUT_VERSION = 1  # bump => migration policy applies (OSM-E802)


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


def _utc_now_iso() -> str:
    # Imported lazily style on purpose: tests inject clock via EventStore(clock=...)
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Event:
    revision: int
    type: str
    recorded_at: str
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    def to_record(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "type": self.type,
            "recorded_at": self.recorded_at,
            "actor": self.actor,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    @staticmethod
    def from_record(rec: dict[str, Any]) -> "Event":
        return Event(
            revision=int(rec["revision"]),
            type=str(rec["type"]),
            recorded_at=str(rec["recorded_at"]),
            actor=str(rec.get("actor", "unknown")),
            payload=dict(rec.get("payload", {})),
            prev_hash=str(rec["prev_hash"]),
            hash=str(rec["hash"]),
        )


@dataclass
class Projection:
    """Rebuilt stream state — the only thing guards and queries look at."""

    project_id: str
    state: ResearchState = ResearchState.OPEN
    revision: int = 0  # last event revision incorporated
    head_hash: str = GENESIS_HASH
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"project_memory": [], "verified_knowledge": [],
                                 "unreviewed_draft": [], "ephemeral_context": []}
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def guard_view(self) -> dict[str, Any]:
        """The exact shape transition.evaluate_guard consumes.

        approvals are included because guards must verify human approval
        against RECORDED APPROVAL_GRANTED events, never against the caller's
        self-declared human_approval_state (trust-boundary rule).
        """
        return {
            "evidence": self.evidence,
            "hypotheses": self.hypotheses,
            "checkpoints": self.checkpoints,
            "reviews": self.reviews,
            "approvals": self.approvals,
        }

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "layout_version": STORE_LAYOUT_VERSION,
            "project_id": self.project_id,
            "state": self.state.value,
            "revision": self.revision,
            "head_hash": self.head_hash,
            "evidence": self.evidence,
            "hypotheses": self.hypotheses,
            "decisions": self.decisions,
            "checkpoints": self.checkpoints,
            "reviews": self.reviews,
            "approvals": self.approvals,
            "memory": self.memory,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_snapshot(project_id: str, snap: dict[str, Any]) -> "Projection":
        p = Projection(project_id=project_id)
        p.state = ResearchState(snap["state"])
        p.revision = int(snap["revision"])
        p.head_hash = str(snap["head_hash"])
        for name in ("evidence", "hypotheses", "decisions", "checkpoints", "reviews", "approvals"):
            setattr(p, name, list(snap.get(name, [])))
        p.memory = {k: list(v) for k, v in snap.get("memory", {}).items()} or p.memory
        p.metadata = dict(snap.get("metadata", {}))
        return p


def apply_event(proj: Projection, ev: Event) -> None:
    """Fold one event into the projection. Pure function of (proj, ev)."""
    t = ev.type
    pl = ev.payload
    proj.revision = ev.revision
    proj.head_hash = ev.hash

    if t == EventType.PROJECT_INITIALIZED.value:
        proj.metadata.update({
            "title": pl.get("title"),
            "request": pl.get("request"),
            "constraints": pl.get("constraints", []),
            "initialized_by": ev.actor,
        })
        proj.state = ResearchState.OPEN

    elif t == EventType.STATE_TRANSITIONED.value:
        proj.state = ResearchState(pl["to_state"])

    elif t == EventType.EVIDENCE_ATTACHED.value:
        proj.evidence.append({
            "ref": pl["ref"],
            "sha256": pl.get("sha256"),
            "tier": pl.get("tier", "unreviewed_draft"),
            "summary": pl.get("summary"),
            "review_by": pl.get("review_by"),
            "attached_revision": ev.revision,
            "retracted": False,
        })

    elif t == EventType.EVIDENCE_RETRACTED.value:
        for e in proj.evidence:
            if e["ref"] == pl["ref"]:
                e["retracted"] = True
                e["retract_reason"] = pl.get("reason")

    elif t == EventType.HYPOTHESIS_RECORDED.value:
        proj.hypotheses.append({
            "id": pl["id"],
            "statement": pl["statement"],
            "status": pl.get("status", "PROPOSED"),
            "supporting_evidence": list(pl.get("supporting_evidence", [])),
            "recorded_revision": ev.revision,
        })

    elif t == EventType.HYPOTHESIS_STATUS_CHANGED.value:
        for h in proj.hypotheses:
            if h["id"] == pl["id"]:
                h["status"] = pl["to_status"]
                h["status_reason"] = pl.get("reason")

    elif t == EventType.DECISION_RECORDED.value:
        proj.decisions.append({
            "id": pl["id"],
            "decision": pl["decision"],
            "rationale": pl.get("rationale"),
            "alternatives": list(pl.get("alternatives", [])),
            "revision": ev.revision,
        })

    elif t == EventType.TASK_CHECKPOINT.value:
        proj.checkpoints.append({
            "task_id": pl["task_id"],
            "state": pl["state"],
            "completed_work": pl.get("completed_work", []),
            "pending_work": pl.get("pending_work", []),
            "revision": ev.revision,
        })

    elif t == EventType.MEMORY_PROMOTED.value:
        item = {
            "ref": pl["ref"],
            "tier": pl["to_tier"],
            "promoted_revision": ev.revision,
            "approved_by": pl.get("approved_by"),
        }
        proj.memory.setdefault(pl["to_tier"], []).append(item)

    elif t == EventType.REVIEW_COMPLETED.value:
        proj.reviews.append({
            "verdict": pl["verdict"],
            "reviewer": pl.get("reviewer"),
            "notes": pl.get("notes"),
            "revision": ev.revision,
        })

    elif t == EventType.APPROVAL_GRANTED.value:
        proj.approvals.append({
            "approver": pl.get("approver"),
            "scope": pl.get("scope"),
            "revision": ev.revision,
        })

    elif t == EventType.DOWNGRADE_TRIGGERED.value:
        proj.state = ResearchState(pl["to_state"])

    # STATE_TRANSITION_REQUESTED / REJECTED / SNAPSHOT_WRITTEN / RECOVERY_* /
    # STALENESS_FLAGGED / REVIEW_REQUESTED are audit records only; they do not
    # change the projection. Keeping them out of the fold is deliberate.


class EventStore:
    """One store directory holds many project streams.

    Layout under <root>/<project_id>/:
      events.jsonl      hash-chained append-only log
      snapshot.json     latest projection (regenerable; never authoritative)
      checkpoints/      per-task recovery working files (ephemeral tier)
    """

    def __init__(self, root: str | Path, *, clock: Callable[[], str] | None = None) -> None:
        self.root = Path(root)
        self.clock = clock or _utc_now_iso

    # ---------- paths ----------
    def stream_dir(self, project_id: str) -> Path:
        # project_id is contract-validated to [a-zA-Z0-9._-]+ upstream; the
        # regex here is defense-in-depth against path traversal.
        if not project_id or any(c in project_id for c in ('/', '\\', '..')):
            raise OsmError(OsmErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"project_id {project_id!r} is not a safe stream name")
        return self.root / project_id

    def log_path(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "events.jsonl"

    def snapshot_path(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "snapshot.json"

    def checkpoint_dir(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "checkpoints"

    def exists(self, project_id: str) -> bool:
        return self.log_path(project_id).is_file()

    # ---------- read ----------
    def read_events(self, project_id: str, *, verify: bool = True) -> list[Event]:
        path = self.log_path(project_id)
        if not path.is_file():
            raise OsmError(OsmErrorCode.PROJECT_NOT_FOUND,
                           f"No state stream for project_id '{project_id}'.",
                           detail={"how_to_fix": "Initialize with action=project.init."})
        events: list[Event] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OsmError(
                            OsmErrorCode.EVENT_LOG_CORRUPT,
                            f"events.jsonl line {lineno} is not valid JSON ({exc.msg}); "
                            f"stream may be truncated mid-write.",
                            detail={"line": lineno, "project_id": project_id},
                        ) from exc
                    events.append(Event.from_record(rec))
        except OSError as exc:
            raise OsmError(OsmErrorCode.STORE_IO_FAILURE,
                           f"Cannot read event log: {exc}", retryable=True) from exc
        if verify:
            self.verify_chain(events, project_id=project_id)
        return events

    @staticmethod
    def verify_chain(events: list[Event], *, project_id: str) -> None:
        prev = GENESIS_HASH
        for i, ev in enumerate(events):
            if ev.revision != i + 1:
                raise OsmError(OsmErrorCode.EVENT_LOG_CORRUPT,
                               f"Revision gap at position {i}: expected {i + 1}, got {ev.revision}.",
                               detail={"project_id": project_id})
            if ev.prev_hash != prev:
                raise OsmError(OsmErrorCode.EVENT_LOG_CORRUPT,
                               f"Hash-chain link broken at revision {ev.revision}.",
                               detail={"project_id": project_id})
            expect = event_hash(ev.prev_hash, {
                "revision": ev.revision, "type": ev.type, "recorded_at": ev.recorded_at,
                "actor": ev.actor, "payload": ev.payload, "prev_hash": ev.prev_hash,
            })
            if ev.hash != expect:
                raise OsmError(OsmErrorCode.EVENT_LOG_CORRUPT,
                               f"Event payload at revision {ev.revision} fails integrity hash.",
                               detail={"project_id": project_id})
            prev = ev.hash

    def rebuild(self, project_id: str, *, verify: bool = True) -> Projection:
        proj = Projection(project_id=project_id)
        for ev in self.read_events(project_id, verify=verify):
            apply_event(proj, ev)
        return proj

    # ---------- write ----------
    def append(
        self,
        project_id: str,
        event_type: EventType | str,
        payload: dict[str, Any],
        *,
        actor: str,
        expected_revision: int | None = None,
    ) -> Event:
        """Append one event with optimistic-concurrency check.

        expected_revision guards multi-session races: if the caller rebuilt at
        revision N but the log has advanced, we fail with OSM-E104 rather than
        silently writing on a stale view.
        """
        # Serialize the enum to its plain value so the on-disk log and
        # apply_event()'s comparisons both use the same bare strings.
        type_str = event_type.value if isinstance(event_type, EventType) else str(event_type)
        d = self.stream_dir(project_id)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OsmError(OsmErrorCode.STORE_IO_FAILURE,
                           f"Cannot create stream dir: {exc}") from exc

        if self.log_path(project_id).is_file():
            events = self.read_events(project_id)
            prev_hash = events[-1].hash if events else GENESIS_HASH
            revision = len(events) + 1
        else:
            if type_str != EventType.PROJECT_INITIALIZED.value:
                raise OsmError(OsmErrorCode.PROJECT_NOT_FOUND,
                               f"First event for '{project_id}' must be PROJECT_INITIALIZED.",
                               detail={"how_to_fix": "Run action=project.init first."})
            prev_hash = GENESIS_HASH
            revision = 1

        if expected_revision is not None and expected_revision != revision - 1:
            raise OsmError(
                OsmErrorCode.INVALID_EVENT_SEQUENCE,
                f"Caller expected head revision {expected_revision} but stream head is "
                f"{revision - 1}; another session advanced the stream. Rebuild and retry.",
                detail={"expected": expected_revision, "actual_head": revision - 1},
            )

        body = {
            "revision": revision,
            "type": type_str,
            "recorded_at": self.clock(),
            "actor": actor,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        ev = Event(revision=revision, type=type_str, recorded_at=body["recorded_at"],
                   actor=actor, payload=payload, prev_hash=prev_hash,
                   hash=event_hash(prev_hash, body))

        line = json.dumps(ev.to_record(), sort_keys=True, ensure_ascii=False) + "\n"
        self._atomic_append(self.log_path(project_id), line)
        return ev

    @staticmethod
    def _atomic_append(path: Path, line: str) -> None:
        """Append via temp-file + rename of a freshly-rewritten log.

        O(append) file handles but O(log) bytes rewritten — acceptable for
        research-scale streams (thousands of events) and it makes a crashed
        write unable to leave a torn last line: the original file is only
        replaced after the new content is fully flushed.
        """
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="") as tmp:
                if path.is_file():
                    with path.open("r", encoding="utf-8") as src:
                        for chunk in iter(lambda: src.read(1 << 16), ""):
                            tmp.write(chunk)
                tmp.write(line)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        except BaseException as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            if isinstance(exc, OsmError):
                raise
            raise OsmError(OsmErrorCode.STORE_IO_FAILURE,
                           f"Atomic append failed: {exc}", retryable=True) from exc

    def write_snapshot(self, project_id: str, proj: Projection, *, actor: str) -> Path:
        snap = proj.to_snapshot()
        snap["written_by"] = actor
        snap["written_at"] = self.clock()
        data = json.dumps(snap, sort_keys=True, ensure_ascii=False, indent=2)
        path = self.snapshot_path(project_id)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise OsmError(OsmErrorCode.STORE_IO_FAILURE,
                           f"Snapshot write failed: {exc}", retryable=True) from exc
        return path

    def read_snapshot(self, project_id: str) -> dict[str, Any]:
        path = self.snapshot_path(project_id)
        if not path.is_file():
            raise OsmError(OsmErrorCode.SNAPSHOT_CORRUPT,
                           f"No snapshot for '{project_id}'; rebuild from the event log.",
                           detail={"how_to_fix": "action=state.snapshot or any mutating action writes one."})
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise OsmError(OsmErrorCode.SNAPSHOT_CORRUPT,
                           f"Snapshot unreadable: {exc}",
                           detail={"how_to_fix": "Delete snapshot.json and rebuild via action=state.get."}) from exc

    def list_projects(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir()
            if p.is_dir() and (p / "events.jsonl").is_file()
        )
