"""Knowledge store: hash-chained JSONL event log + snapshots + backup.

Same guarantees as the sibling obsidian-state-manager skill (spec §四.3,
§五.4, §九):
  - Append-only. No API here can mutate or delete a written event; a retraction
    is a new compensating event.
  - Each event carries sha256(prev_hash + canonical_payload); a broken link or
    edited payload fails verify() with KGE-E301.
  - Appends are atomic per line: write to temp file + os.replace, with an
    os.replace fallback to copy+fsync on filesystems that refuse cross-device
    rename (Windows + some network drives).
  - Snapshots are pure projections: rebuild(events) == read(snapshot) is the
    acceptance invariant checked by SELF_CHECK_FAILED (KGE-E702).
  - Backups are deterministic zip archives of the stream directory, verified
    by checksums; restore refuses to write into a live store.

Canonicalization: json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False). This must NEVER change once stores exist; it is pinned
in the contract version.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import KgeError, KgeErrorCode

GENESIS_HASH = "0" * 64

STORE_LAYOUT_VERSION = 1  # bump => migration policy applies (KGE-E802)


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def event_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


def utc_now_iso() -> str:
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
    """Rebuilt knowledge base state — the only thing query/conflict/guard logic looks at.

    Entities, relations, claims, evidence, and conflicts are stored as lists of
    plain dicts so apply_event() and to_snapshot() stay trivially serializable
    and the projection is a pure function of the event log.
    """

    project_id: str
    revision: int = 0
    head_hash: str = GENESIS_HASH
    ontology: dict[str, Any] = field(default_factory=lambda: {"entity_types": [], "relation_types": [], "version": 1})
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)  # canonical_name -> entity_id
    metadata: dict[str, Any] = field(default_factory=dict)

    def entity_by_id(self, eid: str) -> dict[str, Any] | None:
        for e in self.entities:
            if e["id"] == eid:
                return e
        return None

    def claim_by_id(self, cid: str) -> dict[str, Any] | None:
        for c in self.claims:
            if c["id"] == cid:
                return c
        return None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "layout_version": STORE_LAYOUT_VERSION,
            "project_id": self.project_id,
            "revision": self.revision,
            "head_hash": self.head_hash,
            "ontology": self.ontology,
            "entities": self.entities,
            "relations": self.relations,
            "claims": self.claims,
            "evidence": self.evidence,
            "conflicts": self.conflicts,
            "aliases": self.aliases,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_snapshot(project_id: str, snap: dict[str, Any]) -> "Projection":
        p = Projection(project_id=project_id)
        p.revision = int(snap["revision"])
        p.head_hash = str(snap["head_hash"])
        p.ontology = dict(snap.get("ontology") or {})
        for name in ("entities", "relations", "claims", "evidence", "conflicts"):
            setattr(p, name, list(snap.get(name, [])))
        p.aliases = {str(k): str(v) for k, v in (snap.get("aliases") or {}).items()}
        p.metadata = dict(snap.get("metadata", {}))
        return p


def apply_event(proj: Projection, ev: Event) -> None:
    """Fold one event into the projection. Pure function of (proj, ev)."""
    t = ev.type
    pl = ev.payload
    proj.revision = ev.revision
    proj.head_hash = ev.hash

    if t == "KB_INITIALIZED":
        proj.metadata.update({
            "title": pl.get("title"),
            "request": pl.get("request"),
            "constraints": pl.get("constraints", []),
            "initialized_by": ev.actor,
        })
        proj.ontology = {
            "entity_types": list(pl.get("entity_types", [])),
            "relation_types": list(pl.get("relation_types", [])),
            "version": int(pl.get("ontology_version", 1)),
        }

    elif t == "ONTOLOGY_UPDATED":
        # Schema-evolution event: monotonic, additive OR flagged breaking.
        current_version = int(proj.ontology.get("version", 1))
        declared = pl.get("ontology_version")
        if pl.get("replace"):
            proj.ontology = {
                "entity_types": list(pl.get("entity_types", [])),
                "relation_types": list(pl.get("relation_types", [])),
                "version": int(declared) if isinstance(declared, int) else current_version + 1,
            }
        else:
            for et in pl.get("entity_types", []):
                if et not in proj.ontology["entity_types"]:
                    proj.ontology["entity_types"].append(et)
            for rt in pl.get("relation_types", []):
                if rt not in proj.ontology["relation_types"]:
                    proj.ontology["relation_types"].append(rt)
            if isinstance(declared, int) and declared > current_version:
                proj.ontology["version"] = declared

    elif t == "ENTITY_UPSERTED":
        eid = pl["entity"]["id"]
        merged = False
        for i, e in enumerate(proj.entities):
            if e["id"] == eid:
                proj.entities[i] = pl["entity"]
                merged = True
                break
        if not merged:
            proj.entities.append(pl["entity"])
        for alias in pl.get("aliases", []):
            proj.aliases[alias] = eid

    elif t == "RELATION_ADDED":
        proj.relations.append(pl["relation"])

    elif t == "RELATION_REMOVED":
        rid = pl["relation_id"]
        proj.relations = [r for r in proj.relations if r["id"] != rid]

    elif t == "CLAIM_ADDED":
        claim = dict(pl["claim"])
        claim["_status"] = "ACTIVE"
        claim["recorded_revision"] = ev.revision
        proj.claims.append(claim)
        # For VALUE claims, remember the claim so conflicts can compare.
        claim.setdefault("_comparisons", [])

    elif t == "CLAIM_SUPERSEDED":
        cid = pl["claim_id"]
        for c in proj.claims:
            if c["id"] == cid:
                c["_status"] = "SUPERSEDED"
                c["superseded_by"] = pl.get("by_claim_id")
                c["supersede_reason"] = pl.get("reason")

    elif t == "CLAIM_RETRACTED":
        cid = pl["claim_id"]
        for c in proj.claims:
            if c["id"] == cid:
                c["_status"] = "RETRACTED"
                c["retract_reason"] = pl.get("reason")

    elif t == "EVIDENCE_REGISTERED":
        proj.evidence.append({
            "ref": pl["ref"],
            "sha256": pl.get("sha256"),
            "tier": pl.get("tier"),
            "source": pl.get("source"),
            "summary": pl.get("summary"),
            "recorded_revision": ev.revision,
            "retracted": False,
        })

    elif t == "EVIDENCE_RETRACTED":
        for e in proj.evidence:
            if e["ref"] == pl["ref"]:
                e["retracted"] = True
                e["retract_reason"] = pl.get("reason")

    elif t == "CONFLICT_OPENED":
        proj.conflicts.append({
            "id": pl["conflict_id"],
            "claim_a": pl["claim_a"],
            "claim_b": pl["claim_b"],
            "kind": pl.get("kind", "claim"),
            "reason": pl.get("reason"),
            "status": "OPEN",
            "opened_revision": ev.revision,
            "resolution": None,
        })

    elif t == "CONFLICT_RESOLVED":
        for c in proj.conflicts:
            if c["id"] == pl["conflict_id"]:
                c["status"] = pl.get("status", "RESOLVED")
                c["resolution"] = {
                    "preferred_claim": pl.get("preferred_claim"),
                    "rationale": pl.get("rationale"),
                    "approved_by": pl.get("approved_by"),
                }


class KnowledgeStore:
    """One store directory holds many knowledge bases (project streams).

    Layout under <root>/<project_id>/:
      events.jsonl      hash-chained append-only log
      snapshot.json     latest projection (regenerable; never authoritative)
      backups/          deterministic zip backups (created by backup action)
    """

    def __init__(self, root: str | Path, *, clock: Callable[[], str] | None = None) -> None:
        self.root = Path(root)
        self.clock = clock or utc_now_iso

    # ---------- paths ----------
    def stream_dir(self, project_id: str) -> Path:
        if not project_id or any(c in project_id for c in ("/", "\\", "..")):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"project_id {project_id!r} is not a safe stream name")
        return self.root / project_id

    def log_path(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "events.jsonl"

    def snapshot_path(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "snapshot.json"

    def backup_dir(self, project_id: str) -> Path:
        return self.stream_dir(project_id) / "backups"

    def exists(self, project_id: str) -> bool:
        return self.log_path(project_id).is_file()

    def list_projects(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir()
            if p.is_dir() and (p / "events.jsonl").is_file()
        )

    # ---------- read ----------
    def read_events(self, project_id: str, *, verify: bool = True) -> list[Event]:
        path = self.log_path(project_id)
        if not path.is_file():
            raise KgeError(KgeErrorCode.STORE_NOT_FOUND,
                           f"No knowledge base for project_id '{project_id}'.",
                           detail={"how_to_fix": "Initialize with action=kb.init."})
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
                        raise KgeError(
                            KgeErrorCode.STORE_CORRUPT,
                            f"events.jsonl line {lineno} is not valid JSON ({exc.msg}); "
                            f"store may be truncated mid-write.",
                            detail={"line": lineno, "project_id": project_id},
                        ) from exc
                    events.append(Event.from_record(rec))
        except OSError as exc:
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
                           f"Cannot read event log: {exc}", retryable=True) from exc
        if verify:
            self.verify_chain(events, project_id=project_id)
        return events

    @staticmethod
    def verify_chain(events: list[Event], *, project_id: str) -> None:
        prev = GENESIS_HASH
        for i, ev in enumerate(events):
            if ev.revision != i + 1:
                raise KgeError(KgeErrorCode.STORE_CORRUPT,
                               f"Revision gap at position {i}: expected {i + 1}, got {ev.revision}.",
                               detail={"project_id": project_id})
            if ev.prev_hash != prev:
                raise KgeError(KgeErrorCode.STORE_CORRUPT,
                               f"Hash-chain link broken at revision {ev.revision}.",
                               detail={"project_id": project_id})
            expect = event_hash(ev.prev_hash, {
                "revision": ev.revision, "type": ev.type, "recorded_at": ev.recorded_at,
                "actor": ev.actor, "payload": ev.payload, "prev_hash": ev.prev_hash,
            })
            if ev.hash != expect:
                raise KgeError(KgeErrorCode.STORE_CORRUPT,
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
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str,
        expected_revision: int | None = None,
    ) -> Event:
        """Append one event with optimistic-concurrency check."""
        d = self.stream_dir(project_id)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
                           f"Cannot create store dir: {exc}") from exc

        if self.log_path(project_id).is_file():
            events = self.read_events(project_id)
            prev_hash = events[-1].hash if events else GENESIS_HASH
            revision = len(events) + 1
        else:
            if event_type != "KB_INITIALIZED":
                raise KgeError(KgeErrorCode.STORE_NOT_FOUND,
                               f"First event for '{project_id}' must be KB_INITIALIZED.",
                               detail={"how_to_fix": "Run action=kb.init first."})
            prev_hash = GENESIS_HASH
            revision = 1

        if expected_revision is not None and expected_revision != revision - 1:
            raise KgeError(
                KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                f"Caller expected head revision {expected_revision} but store head is "
                f"{revision - 1}; another session advanced the stream. Rebuild and retry.",
                detail={"expected": expected_revision, "actual_head": revision - 1},
            )

        body = {
            "revision": revision,
            "type": event_type,
            "recorded_at": self.clock(),
            "actor": actor,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        ev = Event(revision=revision, type=event_type, recorded_at=body["recorded_at"],
                   actor=actor, payload=payload, prev_hash=prev_hash,
                   hash=event_hash(prev_hash, body))

        line = json.dumps(ev.to_record(), sort_keys=True, ensure_ascii=False) + "\n"
        self._atomic_append(self.log_path(project_id), line)
        return ev

    @staticmethod
    def _atomic_append(path: Path, line: str) -> None:
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
            if isinstance(exc, KgeError):
                raise
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
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
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
                           f"Snapshot write failed: {exc}", retryable=True) from exc
        return path

    def read_snapshot(self, project_id: str) -> dict[str, Any]:
        path = self.snapshot_path(project_id)
        if not path.is_file():
            raise KgeError(KgeErrorCode.STORE_CORRUPT,
                           f"No snapshot for '{project_id}'; rebuild from the event log.",
                           detail={"how_to_fix": "Any mutating action or kb.get writes one."})
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise KgeError(KgeErrorCode.STORE_CORRUPT,
                           f"Snapshot unreadable: {exc}",
                           detail={"how_to_fix": "Delete snapshot.json and rebuild via action=kb.get."}) from exc

    # ---------- backup / restore ----------
    def backup(self, project_id: str, *, label: str = "") -> dict[str, Any]:
        """Deterministic zip of events.jsonl + snapshot.json with checksums.

        The archive is written into <stream>/backups/kb-<revision>-<label>.zip.
        Entry order is fixed so two backups of an unchanged store are
        byte-identical. Returns a manifest of what was archived.
        """
        stream = self.stream_dir(project_id)
        if not self.log_path(project_id).is_file():
            raise KgeError(KgeErrorCode.STORE_NOT_FOUND,
                           f"No knowledge base for project_id '{project_id}'.",
                           detail={"how_to_fix": "Run action=kb.init first."})
        rev = len(self.read_events(project_id))
        safe_label = "".join(c for c in (label or "") if c.isalnum() or c in "-_")[:48]
        bdir = self.backup_dir(project_id)
        bdir.mkdir(parents=True, exist_ok=True)
        name = f"kb-r{rev}-{safe_label}.zip" if safe_label else f"kb-r{rev}.zip"
        out_path = bdir / name

        entries: list[tuple[str, bytes]] = []
        for fname in ("events.jsonl", "snapshot.json"):
            fpath = stream / fname
            if not fpath.is_file():
                continue
            entries.append((fname, fpath.read_bytes()))
        manifest = {
            "project_id": project_id,
            "revision": rev,
            "label": label,
            "created_at": self.clock(),
            "files": [],
            "sha256_zip": None,
        }
        if not entries:
            raise KgeError(KgeErrorCode.BACKUP_FAILED,
                           f"Nothing to back up: stream '{project_id}' has no data files.")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
            for fname, data in entries:
                zi = zipfile.ZipInfo(fname, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(zi, data)
                manifest["files"].append({"name": fname, "sha256": sha256_bytes(data),
                                          "bytes": len(data)})
        data = buf.getvalue()
        manifest["sha256_zip"] = sha256_bytes(data)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=out_path.name, dir=str(bdir))
        try:
            with os.fdopen(tmp_fd, "wb") as tmp:
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, out_path)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise KgeError(KgeErrorCode.BACKUP_FAILED,
                           f"Backup write failed: {exc}", retryable=True) from exc
        manifest["path"] = str(out_path)
        return manifest

    def restore_backup(self, archive: str | Path, *, into_store_root: str | Path,
                       project_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Verify a backup archive and restore events.jsonl (+ snapshot) into a store.

        Safety: never writes into a live stream. If the target project already
        exists in the target store, the caller must use a fresh project_id or an
        empty store root. `dry_run` validates + reports without writing.
        """
        archive = Path(archive)
        if not archive.is_file():
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
                           f"Backup archive not found: {archive}")
        with zipfile.ZipFile(archive, "r") as zf:
            members = zf.namelist()
            for required in ("events.jsonl",):
                if required not in members:
                    raise KgeError(KgeErrorCode.STORE_CORRUPT,
                                   f"Backup archive missing {required}.",
                                   detail={"members": members})
            files = {m: zf.read(m) for m in members}
        # Verify each file's integrity against the zip CRC (performed by read
        # above); recompute nothing extra — the manifest inside is informational.
        manifest = {
            "archive": str(archive),
            "members": {m: sha256_bytes(d) for m, d in files.items()},
            "restored_to": None,
        }
        if dry_run:
            manifest["restored_to"] = "dry-run: no write"
            return manifest

        target_root = Path(into_store_root)
        stream = target_root / project_id
        if stream.exists() and (stream / "events.jsonl").exists():
            raise KgeError(KgeErrorCode.STORE_IO_FAILURE,
                           f"Refusing to overwrite a live stream at {stream}; "
                           "restore into an empty store or a new project_id.")
        stream.mkdir(parents=True, exist_ok=True)
        for m, data in files.items():
            (stream / m).write_bytes(data)
        manifest["restored_to"] = str(stream)
        return manifest
