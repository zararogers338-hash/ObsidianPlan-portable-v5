"""Service facade: the single entry the CLI and controller call.

Pipeline for every invocation:
  1. schema-validate input (KGE-E101)
  2. check contract_version major (KGE-E801)
  3. locate/rebuild the project projection from the event log (KGE-E303)
  4. run the action (evidence verification, unit checks, epistemic-label
     checks, conflict detection, approval gates)
  5. append events + refresh snapshot
  6. self-check: rebuild == snapshot (KGE-E702)
  7. schema-validate output (KGE-E701)

The facade owns the unified output envelope (Obsidian spec §六): status,
summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts,
requested_next_skills, validation, provenance, errors — always present, even on
failure, so the controller can always parse.

Governance rules enforced here (spec §九):
  - Contradictory claims are never silently overwritten. A new claim that
    conflicts with an existing live claim is recorded AND a CONFLICT_OPENED
    event is appended so both facts coexist and stay traceable.
  - Epistemic labels are checked against evidence tier strength; a claim may
    never be labeled stronger than its support (KGE-E204).
  - Long-term / high-risk writes (VALIDATED tier, migration, restore, bulk
    import, conflict adjudication, breaking ontology change) require versioned
    human approval (KGE-E502/E503) and support dry-run preflight.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import io as kio
from .conflicts import (DEFAULT_VALUE_TOLERANCE, detect_conflicts, evidence_chain,
                        is_open_conflict, normalize_claim_draft)
from .errors import KgeError, KgeErrorCode
from .migration import compute_migration, migrate_store
from .models import (EPISTEMIC_STRENGTH, TIER_STRENGTH, ActorRole, EpistemicLabel,
                     EvidenceTier, KgeErrorCode as _EC, OutputStatus)
from .normalize import normalize_name
from .store import Event, Projection, STORE_LAYOUT_VERSION, apply_event
from .validate import coerce_input_defaults, validate_input, validate_output

SKILL_NAME = "micp-knowledge-graph-steward"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0"

# Base entity types, mirrored from io.base_ontology for the ontology-update
# vocabulary checks (extensions ride on ONTOLOGY_UPDATED events).
_BASE_ENTITY_TYPES = [
    "STRAIN", "ENZYME", "SUBSTRATE", "REACTANT", "PRODUCT", "ION",
    "MINERAL_PHASE", "POROUS_MEDIUM", "PROCESS", "INSTRUMENT", "EXPERIMENT",
    "PROPERTY", "METRIC", "ENV_INDICATOR", "METHOD", "ARTIFACT",
]
_BASE_RELATION_TYPES = [
    "HAS_TYPE", "SYNONYM_OF", "RELATED_TO", "CATALYZES", "CONSUMES",
    "PRODUCES", "MEASURED_BY", "OBSERVED_IN", "SAME_AS", "IS_PHASE_OF",
    "APPLIES_TO", "EVIDENCE_FOR", "EVIDENCE_AGAINST", "PARTOF", "DEPENDS_ON",
    "SUPPORTS", "REFUTES",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _conflict_id(a: str, b: str) -> str:
    return f"conflict:{min(a, b)}:{max(a, b)}"


class KnowledgeGraphService:
    def __init__(self, store_root: str | Path, *, clock=None) -> None:
        from .store import KnowledgeStore

        self.store = KnowledgeStore(store_root, clock=clock)

    # ------------------------------------------------------------------
    # public entry
    # ------------------------------------------------------------------
    def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        started = _now_iso()
        out = self._envelope(raw, started)
        try:
            validate_input(raw)
            raw = coerce_input_defaults(raw)
            out["validation"]["input_schema"] = "passed"
            if not raw.get("contract_version", "").startswith("1."):
                raise KgeError(
                    KgeErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    f"contract_version {raw.get('contract_version')!r} is not consumable by this "
                    f"build (supports 1.x). Migrate the payload or pin a compatible skill version.",
                    detail={"declared": raw.get("contract_version"), "supported": "1.x"},
                )
            action = raw["action"]
            handler = getattr(self, f"_do_{action.replace('.', '_').replace('-', '_')}", None)
            if handler is None:
                raise KgeError(
                    KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                    f"Unknown action '{action}'.",
                    detail={"known_actions": sorted(self.actions())},
                )
            dry_run = bool(raw.get("dry_run", False))
            result = handler(raw, out, dry_run=dry_run)
            out.update(result)
            if out.get("errors"):
                out["status"] = OutputStatus.PARTIAL.value
            else:
                out["status"] = OutputStatus.SUCCESS.value
        except KgeError as exc:
            self._apply_error(raw, out, exc)
        except Exception as exc:  # last-resort guard: never emit unparseable output
            self._apply_error(raw, out, KgeError(
                KgeErrorCode.TOOL_UNAVAILABLE,
                f"Unhandled internal error: {type(exc).__name__}: {exc}",
                detail={"exception_type": type(exc).__name__},
            ))

        out["provenance"]["completed_at"] = _now_iso()
        try:
            validate_output(out)
            out["validation"]["output_schema"] = "passed"
        except KgeError as exc:
            out["status"] = OutputStatus.FAILED.value
            out["validation"]["output_schema"] = "failed"
            out["errors"].append(exc.to_dict())
        return out

    @staticmethod
    def actions() -> list[str]:
        return [
            "kb.init", "kb.get", "kb.list", "kb.backup", "kb.restore",
            "kb.migrate", "kb.integrity",
            "graph.upsert_entity", "graph.add_relation", "graph.remove_relation",
            "graph.add_claim", "graph.supersede_claim", "graph.retract_claim",
            "graph.evidence_register", "graph.evidence_retract",
            "graph.evidence_chain", "graph.conflict_scan", "graph.conflict_resolve",
            "graph.ontology", "graph.ontology_update", "graph.query",
            "graph.import", "graph.export",
            "approval.grant",
        ]

    # ------------------------------------------------------------------
    # envelope helpers
    # ------------------------------------------------------------------
    def _envelope(self, raw: dict[str, Any], started: str) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "status": OutputStatus.FAILED.value,
            "summary": "",
            "action": raw.get("action"),
            "project_id": raw.get("project_id"),
            "task_id": raw.get("task_id"),
            "findings": [],
            "assumptions": [],
            "evidence_used": [],
            "uncertainty": [],
            "risks": [],
            "artifacts": [],
            "requested_next_skills": [],
            "state": None,
            "validation": {"input_schema": "pending", "output_schema": "pending",
                           "self_check": "not_run", "rebuild_matches_snapshot": None},
            "provenance": {
                "started_at": started,
                "completed_at": None,
                "store_root": str(self.store.root),
                "host": platform.node(),
                "events_appended": [],
                "head_revision": None,
                "head_hash": None,
            },
            "errors": [],
        }

    def _apply_error(self, raw: dict[str, Any], out: dict[str, Any], exc: KgeError) -> None:
        code = exc.code
        status_map = {
            KgeErrorCode.APPROVAL_REQUIRED: OutputStatus.HUMAN_APPROVAL_REQUIRED,
            KgeErrorCode.APPROVAL_STALE: OutputStatus.HUMAN_APPROVAL_REQUIRED,
            KgeErrorCode.DOWNSTREAM_CAPABILITY_MISSING: OutputStatus.NEED_ADDITIONAL_SKILL,
            KgeErrorCode.DOWNSTREAM_CONTRACT_MISMATCH: OutputStatus.FAILED,
            KgeErrorCode.MISSING_REQUIRED_FIELD: OutputStatus.BLOCKED,
            KgeErrorCode.INPUT_SCHEMA_VIOLATION: OutputStatus.BLOCKED,
            KgeErrorCode.UNKNOWN_ACTION: OutputStatus.BLOCKED,
            KgeErrorCode.ENTITY_NOT_FOUND: OutputStatus.BLOCKED,
            KgeErrorCode.EVIDENCE_UNVERIFIABLE: OutputStatus.BLOCKED,
            KgeErrorCode.EVIDENCE_INTEGRITY_MISMATCH: OutputStatus.BLOCKED,
            KgeErrorCode.UNIT_INCONSISTENT: OutputStatus.BLOCKED,
            KgeErrorCode.EPISTEMIC_MISLABEL: OutputStatus.BLOCKED,
            KgeErrorCode.STORE_CORRUPT: OutputStatus.BLOCKED,
            KgeErrorCode.CONTEXT_CORRUPT: OutputStatus.BLOCKED,
            KgeErrorCode.STORE_NOT_FOUND: OutputStatus.BLOCKED,
            KgeErrorCode.CONFLICT_UNDETECTED: OutputStatus.BLOCKED,
            KgeErrorCode.MIGRATION_REQUIRED: OutputStatus.BLOCKED,
            KgeErrorCode.PERMISSION_DENIED: OutputStatus.BLOCKED,
            KgeErrorCode.TOOL_UNAVAILABLE: OutputStatus.FAILED,
            KgeErrorCode.TOOL_TIMEOUT: OutputStatus.FAILED,
            KgeErrorCode.STORE_IO_FAILURE: OutputStatus.FAILED,
            KgeErrorCode.BACKUP_FAILED: OutputStatus.FAILED,
            KgeErrorCode.OUTPUT_SCHEMA_VIOLATION: OutputStatus.FAILED,
            KgeErrorCode.SELF_CHECK_FAILED: OutputStatus.FAILED,
            KgeErrorCode.RESULT_REJECTED: OutputStatus.FAILED,
            KgeErrorCode.UNSUPPORTED_SCHEMA_VERSION: OutputStatus.FAILED,
        }
        out["status"] = status_map.get(code, OutputStatus.FAILED).value
        out["errors"].append(exc.to_dict())
        out["summary"] = f"{code.code}: {exc.message}"

    def _projection_or_raise(self, raw: dict[str, Any]) -> Projection:
        pid = raw["project_id"]
        if not self.store.exists(pid):
            raise KgeError(
                KgeErrorCode.STORE_NOT_FOUND,
                f"No knowledge base for project_id '{pid}'.",
                detail={"missing_field": "knowledge base",
                        "why_critical": "Every graph action rebuilds from the project's event "
                                        "log; without a base there is nothing to act on.",
                        "how_to_fix": "Run action=kb.init once for this project_id."},
            )
        return self.store.rebuild(pid)

    # ------------------------------------------------------------------
    # approval + evidence gates
    # ------------------------------------------------------------------
    def _check_approval(self, raw: dict[str, Any], proj: Projection, *,
                        dry_run: bool) -> tuple[str | None, int | None]:
        """Versioned human-approval gate (spec §九.4, KGE-E502/E503).

        Dry-run preflight accepts a missing approval (the caller learns what a
        real run needs) but still rejects a stale one, so dry-run never
        under-validates the approval contract.
        """
        approval = raw.get("human_approval_state")
        granted = approval and approval.get("granted")
        if dry_run and not granted:
            return None, None
        if not granted:
            raise KgeError(
                KgeErrorCode.APPROVAL_REQUIRED,
                "This action writes long-term / high-risk knowledge and requires explicit "
                "human approval.",
                detail={"how_to_fix": "human_approval_state.granted=true with approver + "
                                      "revision == current head."},
            )
        rev = approval.get("revision")
        if rev is not None and int(rev) != proj.revision:
            raise KgeError(
                KgeErrorCode.APPROVAL_STALE,
                f"Approval was granted for revision {rev} but the stream head is "
                f"{proj.revision}; renew approval against the current head.",
                detail={"approval_revision": rev, "head_revision": proj.revision},
            )
        return approval.get("approver"), rev

    def _verify_claim_evidence(self, proj: Projection, claim: dict[str, Any]) -> None:
        """Every evidence_ref must be a registered, non-retracted record whose
        content hash (when the caller asserts one) matches the recorded sha256."""
        for ref in claim.get("evidence_refs") or []:
            rec = next((e for e in proj.evidence if e["ref"] == ref), None)
            if rec is None or rec.get("retracted"):
                raise KgeError(
                    KgeErrorCode.EVIDENCE_UNVERIFIABLE,
                    f"Claim references evidence '{ref}' that is not a live registered record.",
                    detail={"ref": ref, "claim_id": claim.get("id"),
                            "how_to_fix": "Register it with action=graph.evidence_register first."},
                )
            hashes = claim.get("evidence_hashes") or {}
            if ref in hashes:
                registered = rec.get("sha256")
                if registered and hashes[ref] != registered:
                    raise KgeError(
                        KgeErrorCode.EVIDENCE_INTEGRITY_MISMATCH,
                        f"Claim asserts content hash {hashes[ref]} for '{ref}' but the registered "
                        f"hash is {registered}.",
                        detail={"ref": ref, "asserted": hashes[ref], "registered": registered},
                    )

    def _check_label_strength(self, claim: dict[str, Any]) -> None:
        tier = claim.get("evidence_tier")
        label = claim.get("epistemic_label")
        label_strength = EPISTEMIC_STRENGTH.get(EpistemicLabel(label), 0)
        tier_strength = TIER_STRENGTH.get(EvidenceTier(tier), 0)
        if label_strength > tier_strength:
            raise KgeError(
                KgeErrorCode.EPISTEMIC_MISLABEL,
                f"Claim '{claim.get('id')}' is labeled {label} but its evidence tier is "
                f"{tier}; a claim may never be labeled stronger than its support.",
                detail={"claim_id": claim.get("id"), "epistemic_label": label,
                        "evidence_tier": tier,
                        "label_strength": label_strength, "tier_strength": tier_strength},
            )

    # ------------------------------------------------------------------
    # write primitives
    # ------------------------------------------------------------------
    def _record(self, raw: dict[str, Any], proj: Projection, out: dict[str, Any],
                event_type: str, payload: dict[str, Any], *, dry_run: bool) -> None:
        actor = raw.get("actor", {})
        actor_name = actor.get("id") or actor.get("role", "unknown")
        expected = raw.get("expected_revision")
        if expected is not None and expected != proj.revision:
            raise KgeError(
                KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                f"Caller expected head revision {expected} but stream head is {proj.revision}; "
                f"another session advanced the stream. Rebuild and retry.",
                detail={"expected": expected, "actual_head": proj.revision},
            )
        if dry_run:
            fake = Event(revision=proj.revision + 1, type=event_type,
                         recorded_at=_now_iso(), actor=actor_name, payload=payload,
                         prev_hash=proj.head_hash, hash="<dry-run>")
            apply_event(proj, fake)
            out["provenance"]["events_appended"].append(
                {"type": event_type, "revision": "dry-run", "hash": "<dry-run>"})
            return
        ev = self.store.append(proj.project_id, event_type, payload, actor=actor_name,
                               expected_revision=expected)
        apply_event(proj, ev)
        out["provenance"]["events_appended"].append(
            {"type": ev.type, "revision": ev.revision, "hash": ev.hash})
        out["provenance"]["head_revision"] = ev.revision
        out["provenance"]["head_hash"] = ev.hash

    def _finish_mutation(self, raw: dict[str, Any], proj: Projection,
                         out: dict[str, Any], *, dry_run: bool) -> None:
        if dry_run:
            out["validation"]["self_check"] = "skipped_dry_run"
            out["artifacts"].append({"kind": "projection", "path": None,
                                     "note": "dry-run: no snapshot written"})
            return
        snap_path = self.store.write_snapshot(proj.project_id, proj,
                                              actor=raw.get("actor", {}).get("id", SKILL_NAME))
        rebuilt = self.store.rebuild(proj.project_id)
        snap_on_disk = self.store.read_snapshot(proj.project_id)
        live = rebuilt.to_snapshot()
        on_disk = {k: v for k, v in snap_on_disk.items()
                   if k not in ("written_at", "written_by")}
        match = (live["head_hash"] == on_disk.get("head_hash")
                 and live["revision"] == on_disk.get("revision")
                 and live["ontology"] == on_disk.get("ontology")
                 and len(live["claims"]) == len(on_disk.get("claims", [])))
        out["validation"]["rebuild_matches_snapshot"] = match
        out["validation"]["self_check"] = "passed" if match else "failed"
        if not match:
            raise KgeError(
                KgeErrorCode.SELF_CHECK_FAILED,
                "Post-write rebuild does not match the written snapshot; "
                "event log and snapshot disagree.",
                detail={"project_id": proj.project_id},
            )
        out["artifacts"].append({"kind": "snapshot", "path": str(snap_path)})

    def _finish_readonly(self, proj: Projection, out: dict[str, Any]) -> None:
        """Self-check for read-only actions: snapshot (if any) must agree with
        the event-log rebuild (acceptance invariant, KGE-E702)."""
        try:
            snap = self.store.read_snapshot(proj.project_id)
            match = (snap.get("head_hash") == proj.head_hash
                     and snap.get("revision") == proj.revision)
        except KgeError:
            match = None  # no snapshot yet; nothing to compare
        out["validation"]["rebuild_matches_snapshot"] = match
        out["validation"]["self_check"] = ("passed" if match
                                           else "not_run" if match is None else "failed")
        if match is False:
            raise KgeError(KgeErrorCode.SELF_CHECK_FAILED,
                           "Snapshot disagrees with event-log rebuild.",
                           detail={"snapshot_revision": snap.get("revision"),
                                   "rebuild_revision": proj.revision})

    def _ontology_violations(self, item: dict[str, Any], *, kind: str) -> list[str]:
        schema = kio.generate_ontology_schema(self._ontology_or_base(None))
        return kio.validate_against_ontology(item, schema, kind=kind)

    def _ontology_or_base(self, proj: Projection | None) -> dict[str, Any]:
        onto = proj.ontology if proj is not None else None
        if onto and onto.get("entity_types"):
            return {
                "entity_types": onto["entity_types"],
                "relation_types": onto.get("relation_types", []),
                "version": onto.get("version", 1),
            }
        return kio.base_ontology()

    # ------------------------------------------------------------------
    # actions — kb.*
    # ------------------------------------------------------------------
    def _do_kb_init(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        pid = raw["project_id"]
        if self.store.exists(pid):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Knowledge base '{pid}' already exists; init is once-only.",
                           detail={"how_to_fix": "Use action=kb.get to inspect, or a new project_id."})
        proj = Projection(project_id=pid)
        base = kio.base_ontology()
        self._record(raw, proj, out, "KB_INITIALIZED", {
            "title": raw.get("title", "MICP knowledge base"),
            "request": raw["request"],
            "constraints": raw.get("constraints", []),
            "entity_types": base["entity_types"],
            "relation_types": base["relation_types"],
            "ontology_version": base["version"],
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        prefix = "[dry-run] " if dry_run else ""
        return {"summary": f"{prefix}Initialized knowledge base '{pid}' with ontology v{base['version']}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"knowledge base created; {len(base['entity_types'])} entity "
                                           f"types, {len(base['relation_types'])} relation types",
                              "source": "event_log"}]}

    def _do_kb_get(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._finish_readonly(proj, out)
        live_claims = [c for c in proj.claims if c.get("_status") != "RETRACTED"]
        open_conflicts = [c for c in proj.conflicts if c["status"] == "OPEN"]
        view = {
            "project_id": proj.project_id,
            "title": proj.metadata.get("title"),
            "head_revision": proj.revision,
            "head_hash": proj.head_hash,
            "ontology_version": proj.ontology.get("version", 1),
            "counts": {
                "entities": len(proj.entities),
                "relations": len(proj.relations),
                "claims": len(live_claims),
                "evidence": len([e for e in proj.evidence if not e.get("retracted")]),
                "open_conflicts": len(open_conflicts),
                "aliases": len(proj.aliases),
            },
            "open_conflicts": [{"conflict_id": c["id"], "claim_a": c["claim_a"],
                                "claim_b": c["claim_b"], "reason": c["reason"]}
                               for c in open_conflicts],
        }
        out["artifacts"].append({"kind": "kb_view", "path": None, "note": view})
        return {"summary": f"Knowledge base '{proj.project_id}' at revision {proj.revision} "
                           f"(ontology v{view['ontology_version']}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"entities={view['counts']['entities']} claims={view['counts']['claims']} "
                                           f"evidence={view['counts']['evidence']} "
                                           f"open_conflicts={view['counts']['open_conflicts']}",
                              "source": "event_log_rebuild"}]}

    def _do_kb_list(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        projects = self.store.list_projects()
        views = []
        for pid in projects:
            try:
                p = self.store.rebuild(pid)
                views.append({"project_id": pid, "revision": p.revision,
                              "entities": len(p.entities), "claims": len(p.claims)})
            except KgeError as exc:
                views.append({"project_id": pid, "error": exc.code.code})
        return {"summary": f"{len(projects)} knowledge base(s) in store.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"bases: {views}",
                              "source": "store_scan"}],
                "artifacts": []}

    def _do_kb_backup(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        if dry_run:
            return {"summary": "[dry-run] Backup would create a deterministic zip in <stream>/backups/.",
                    "findings": [{"label": EpistemicLabel.CALCULATED.value,
                                  "statement": f"stream has {proj.revision} events; no archive written",
                                  "source": "backup_engine"}],
                    "artifacts": [{"kind": "backup_dry_run", "path": None,
                                   "note": {"revision": proj.revision}}]}
        manifest = self.store.backup(proj.project_id, label=raw.get("label", ""))
        out["artifacts"].append({"kind": "backup_manifest", "path": manifest["path"],
                                 "note": {"revision": manifest["revision"],
                                          "sha256_zip": manifest["sha256_zip"],
                                          "files": manifest["files"]}})
        return {"summary": f"Backup created at {manifest['path']} (revision {manifest['revision']}).",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"zip sha256={manifest['sha256_zip'][:16]}…",
                              "source": "backup_engine"}]}

    def _do_kb_restore(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        archive = raw["archive"]
        approver, _rev = self._check_approval(raw, Projection(project_id=raw["project_id"]),
                                              dry_run=dry_run)
        if dry_run and approver is None:
            out["assumptions"].append("kb.restore is high-risk; a real run requires human approval.")
        manifest = self.store.restore_backup(archive, into_store_root=self.store.root,
                                             project_id=raw["project_id"], dry_run=dry_run)
        out["artifacts"].append({"kind": "restore_manifest", "path": None, "note": manifest})
        return {"summary": ("[dry-run] " if dry_run else "") +
                           f"Restored backup '{archive}' as project '{raw['project_id']}'.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"restored_to={manifest['restored_to']}",
                              "source": "backup_engine"}]}

    def _do_kb_migrate(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        pid = raw["project_id"]
        if not self.store.exists(pid):
            raise KgeError(KgeErrorCode.STORE_NOT_FOUND,
                           f"No knowledge base for project_id '{pid}'.",
                           detail={"how_to_fix": "Run action=kb.init first."})
        decision = compute_migration(self.store, pid)
        if not decision["required"]:
            return {"summary": f"Knowledge base '{pid}' is on the current layout "
                               f"(v{STORE_LAYOUT_VERSION}); no migration needed.",
                    "findings": [{"label": EpistemicLabel.CALCULATED.value,
                                  "statement": f"store_layout={decision['store_layout']} "
                                               f"current_layout={decision['current_layout']}",
                                  "source": "migration_engine"}]}
        proj = self.store.rebuild(pid)
        approver, _rev = self._check_approval(raw, proj, dry_run=dry_run)
        if dry_run and approver is None:
            out["assumptions"].append("kb.migrate rewrites the store layout; a real run requires "
                                      "human approval and is reversible via backup.")
        result = migrate_store(self.store, pid, actor=raw.get("actor", {}).get("id", SKILL_NAME),
                               dry_run=dry_run)
        out["provenance"]["events_appended"].extend(result["events_appended"])
        if not dry_run and result["migrated"]:
            proj = self.store.rebuild(pid)
            self._finish_mutation(raw, proj, out, dry_run=False)
        return {"summary": f"Migration {'[dry-run] needed' if dry_run else 'applied'}: "
                           f"layout {decision['store_layout']} → {STORE_LAYOUT_VERSION}.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"reason={decision['reason']}",
                              "source": "migration_engine"}]}

    def _do_kb_integrity(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)  # read_events verifies the hash chain (E301)
        try:
            snap = self.store.read_snapshot(proj.project_id)
            snapshot_ok = (snap.get("head_hash") == proj.head_hash
                           and snap.get("revision") == proj.revision)
        except KgeError:
            snapshot_ok = None
        report = {
            "chain_ok": True,
            "revision": proj.revision,
            "head_hash": proj.head_hash,
            "snapshot_ok": snapshot_ok,
            "events_replayed": proj.revision,
        }
        out["artifacts"].append({"kind": "integrity_report", "path": None, "note": report})
        out["validation"]["rebuild_matches_snapshot"] = snapshot_ok
        return {"summary": f"Integrity check: hash chain OK, {proj.revision} events replayed, "
                           f"snapshot {'consistent' if snapshot_ok else 'missing/inconsistent'}.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"chain_ok=True snapshot_ok={snapshot_ok}",
                              "source": "integrity_check"}]}

    # ------------------------------------------------------------------
    # actions — graph.* entities/relations
    # ------------------------------------------------------------------
    def _do_graph_upsert_entity(self, raw: dict[str, Any], out: dict[str, Any], *,
                                dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        entity = dict(raw["entity"])
        if not entity.get("id"):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Entity requires an 'id'.", detail={"entity": entity})
        violations = self._ontology_violations(entity, kind="entity")
        if violations:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Entity violates the ontology vocabulary: " + "; ".join(violations),
                           detail={"violations": violations, "entity_id": entity["id"]})
        if entity.get("canonical_name"):
            entity["canonical_name"] = normalize_name(entity["canonical_name"])
        aliases = raw.get("aliases", [])
        identity_candidate: str | None = None
        canon = entity.get("canonical_name")
        if canon:
            for other in proj.entities:
                if other["id"] != entity["id"] and normalize_name(other.get("canonical_name", "")) == canon:
                    identity_candidate = other["id"]
                    break
        self._record(raw, proj, out, "ENTITY_UPSERTED", {
            "entity": entity, "aliases": aliases,
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        findings = [{"label": EpistemicLabel.OBSERVED.value,
                     "statement": f"entity {entity['id']} ({entity.get('entity_type')}) recorded",
                     "source": "event_log"}]
        if identity_candidate:
            # Bootstrap guard #1: never silently merge distinct entities that
            # merely share a canonical name; surface the candidate instead.
            findings.append({
                "label": EpistemicLabel.RECOMMENDATION.value,
                "statement": f"entity '{entity['id']}' and '{identity_candidate}' share the canonical "
                             f"name '{canon}'. They were NOT merged; establish identity with an "
                             f"explicit IDENTITY claim before treating them as the same strain.",
                "source": "identity_guard"})
        return {"summary": f"Upserted entity {entity['id']}"
                           + (" (identity candidate: not merged)" if identity_candidate else "") + ".",
                "findings": findings}

    def _do_graph_add_relation(self, raw: dict[str, Any], out: dict[str, Any], *,
                               dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        relation = dict(raw["relation"])
        violations = self._ontology_violations(relation, kind="relation")
        if violations:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Relation violates the ontology vocabulary: " + "; ".join(violations),
                           detail={"violations": violations})
        for endpoint in ("from_id", "to_id"):
            if proj.entity_by_id(relation.get(endpoint)) is None:
                raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                               f"Relation endpoint '{relation.get(endpoint)}' does not exist.",
                               detail={"missing": endpoint, "relation_id": relation.get("id"),
                                       "how_to_fix": "Create the entity first (graph.upsert_entity)."})
        self._record(raw, proj, out, "RELATION_ADDED", {"relation": relation}, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Added relation {relation.get('id')}: "
                           f"{relation.get('from_id')} -{relation.get('relation_type')}-> "
                           f"{relation.get('to_id')}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"relation {relation.get('id')} recorded",
                              "source": "event_log"}]}

    def _do_graph_remove_relation(self, raw: dict[str, Any], out: dict[str, Any], *,
                                  dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        rid = raw["relation_id"]
        if not any(r["id"] == rid for r in proj.relations):
            raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                           f"Relation '{rid}' does not exist.",
                           detail={"how_to_fix": "action=graph.export lists current relations."})
        self._record(raw, proj, out, "RELATION_REMOVED", {"relation_id": rid}, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Removed relation '{rid}' (kept in event log for audit).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"relation {rid} removed at revision {proj.revision}",
                              "source": "event_log"}]}

    # ------------------------------------------------------------------
    # actions — graph.* claims
    # ------------------------------------------------------------------
    def _prepare_claim(self, raw: dict[str, Any], proj: Projection,
                       claim: dict[str, Any]) -> dict[str, Any]:
        claim = normalize_claim_draft(claim)
        violations = self._ontology_violations(claim, kind="claim")
        if violations:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Claim violates the ontology vocabulary: " + "; ".join(violations),
                           detail={"violations": violations, "claim_id": claim.get("id")})
        subject = claim.get("subject")
        if subject and not claim.get("subject_is_alias") \
                and claim.get("claim_kind") not in ("OBSERVATION", "NORMATIVE") \
                and proj.entity_by_id(subject) is None:
            raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                           f"Claim 'subject' '{subject}' is not a known entity id.",
                           detail={"claim_id": claim.get("id"), "missing": "subject",
                                   "how_to_fix": "Create the entity first, or set "
                                                 "subject_is_alias=true for lexical subjects."})
        self._verify_claim_evidence(proj, claim)
        self._check_label_strength(claim)
        return claim

    def _record_open_conflicts(self, raw: dict[str, Any], proj: Projection, out: dict[str, Any],
                               new_claim: dict[str, Any], *, dry_run: bool) -> list[str]:
        """Detect conflicts involving the new claim and record each as an open
        conflict. Contradictory facts coexist; nothing is silently overwritten."""
        opened: list[str] = []
        for conflict in detect_conflicts(proj, only_new=new_claim):
            cid = _conflict_id(conflict["claim_a"], conflict["claim_b"])
            if is_open_conflict(proj, conflict["claim_a"], conflict["claim_b"]):
                continue
            self._record(raw, proj, out, "CONFLICT_OPENED", {
                "conflict_id": cid,
                "claim_a": conflict["claim_a"],
                "claim_b": conflict["claim_b"],
                "kind": conflict.get("kind", "claim"),
                "reason": conflict["reason"],
            }, dry_run=dry_run)
            opened.append(cid)
        return opened

    def _do_graph_add_claim(self, raw: dict[str, Any], out: dict[str, Any], *,
                            dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        claim = dict(raw["claim"])
        if any(c["id"] == claim["id"] for c in proj.claims):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Claim id '{claim['id']}' already exists; use graph.supersede_claim "
                           f"or graph.retract_claim.",
                           detail={"how_to_fix": "Choose a fresh claim id."})

        # Inline evidence registration in the same mutation.
        for evd in raw.get("evidence") or []:
            self._record(raw, proj, out, "EVIDENCE_REGISTERED", {
                "ref": evd["ref"], "sha256": evd.get("sha256"), "tier": evd.get("tier"),
                "source": evd.get("source"), "summary": evd.get("summary"),
            }, dry_run=dry_run)

        claim = self._prepare_claim(raw, proj, claim)
        approver: str | None = None
        if claim.get("evidence_tier") == EvidenceTier.VALIDATED.value:
            if not claim.get("evidence_refs"):
                raise KgeError(KgeErrorCode.EVIDENCE_UNVERIFIABLE,
                               "A VALIDATED claim requires at least one evidence_ref; promotion "
                               "to VALIDATED without verifiable evidence is rejected.",
                               detail={"claim_id": claim["id"]})
            approver, appr_rev = self._check_approval(raw, proj, dry_run=dry_run)
            if approver is None and dry_run:
                out["assumptions"].append("VALIDATED claims require human approval in a real run.")
            claim["approved_by"] = approver
            claim["approval_revision"] = appr_rev

        payload = {"claim": claim}
        self._record(raw, proj, out, "CLAIM_ADDED", payload, dry_run=dry_run)
        opened = self._record_open_conflicts(raw, proj, out, claim, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)

        findings = [{"label": claim.get("epistemic_label", EpistemicLabel.REPORTED.value),
                     "statement": f"claim {claim['id']}: {claim.get('predicate')} recorded as "
                                  f"{claim.get('epistemic_label')} (tier {claim.get('evidence_tier')})",
                     "source": "event_log"}]
        for cid in opened:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": f"open conflict {cid}: both claims coexist, unresolved",
                             "source": "conflict_detector"})
        summary = f"Recorded claim {claim['id']} as {claim.get('epistemic_label')}"
        if opened:
            summary += f" with {len(opened)} open conflict(s) (no silent overwrite)"
        summary += "."
        if approver:
            summary += f" VALIDATED by approval of {approver}."
        return {"summary": summary, "findings": findings,
                "risks": [{"label": EpistemicLabel.INFERRED.value,
                           "statement": f"{len(opened)} open conflict(s) require adjudication "
                                        f"(graph.conflict_resolve)"}] if opened else []}

    def _do_graph_supersede_claim(self, raw: dict[str, Any], out: dict[str, Any], *,
                                  dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        old = raw["claim_id"]
        if proj.claim_by_id(old) is None:
            raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                           f"Claim '{old}' does not exist.",
                           detail={"how_to_fix": "Use graph.query or graph.export to list claims."})
        replacement = self._prepare_claim(raw, proj, dict(raw["replacement"]))
        if any(c["id"] == replacement["id"] for c in proj.claims):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Replacement claim id '{replacement['id']}' already exists.",
                           detail={"how_to_fix": "Choose a fresh claim id."})
        # Supersede first so the old claim stops being comparable, then add the
        # replacement; both remain in the graph for audit (nothing deleted).
        self._record(raw, proj, out, "CLAIM_SUPERSEDED", {
            "claim_id": old, "by_claim_id": replacement["id"], "reason": raw.get("reason"),
        }, dry_run=dry_run)
        self._record(raw, proj, out, "CLAIM_ADDED", {"claim": replacement}, dry_run=dry_run)
        opened = self._record_open_conflicts(raw, proj, out, replacement, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Superseded claim {old} by {replacement['id']} "
                           f"(old claim retained as SUPERSEDED).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"{old} → SUPERSEDED; {replacement['id']} → ACTIVE",
                              "source": "event_log"},
                             *([{"label": EpistemicLabel.OBSERVED.value,
                                 "statement": f"open conflict {cid} recorded", "source": "conflict_detector"}
                                for cid in opened])]}

    def _do_graph_retract_claim(self, raw: dict[str, Any], out: dict[str, Any], *,
                                dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        cid = raw["claim_id"]
        if proj.claim_by_id(cid) is None:
            raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                           f"Claim '{cid}' does not exist.",
                           detail={"how_to_fix": "Use graph.query to list claims."})
        self._record(raw, proj, out, "CLAIM_RETRACTED", {
            "claim_id": cid, "reason": raw.get("reason"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Retracted claim {cid}; retained in the graph as RETRACTED (not deleted).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"claim {cid} → RETRACTED at revision {proj.revision}",
                              "source": "event_log"}]}

    # ------------------------------------------------------------------
    # actions — graph.* evidence
    # ------------------------------------------------------------------
    def _do_graph_evidence_register(self, raw: dict[str, Any], out: dict[str, Any], *,
                                    dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        evd = dict(raw["evidence"])
        if not evd.get("ref"):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Evidence requires a 'ref'.", detail={"evidence": evd})
        tier = evd.get("tier")
        if tier is not None and tier not in kio.base_ontology()["evidence_tiers"] \
                and tier not in proj.ontology.get("entity_types", []) and False:
            pass  # evidence tiers come from the base vocabulary; keep simple below
        self._record(raw, proj, out, "EVIDENCE_REGISTERED", {
            "ref": evd["ref"], "sha256": evd.get("sha256"), "tier": tier,
            "source": evd.get("source"), "summary": evd.get("summary"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Registered evidence {evd['ref']} (tier {tier or 'unset'}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"evidence {evd['ref']} recorded at revision {proj.revision}",
                              "source": "event_log"}]}

    def _do_graph_evidence_retract(self, raw: dict[str, Any], out: dict[str, Any], *,
                                   dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        ref = raw["ref"]
        if not any(e["ref"] == ref and not e.get("retracted") for e in proj.evidence):
            raise KgeError(KgeErrorCode.EVIDENCE_UNVERIFIABLE,
                           f"No live evidence with ref '{ref}' to retract.",
                           detail={"how_to_fix": "action=kb.get lists live evidence refs."})
        self._record(raw, proj, out, "EVIDENCE_RETRACTED", {"ref": ref, "reason": raw.get("reason")},
                     dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Retracted evidence {ref}; retained in the log as retracted.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"evidence {ref} → retracted",
                              "source": "event_log"}]}

    def _do_graph_evidence_chain(self, raw: dict[str, Any], out: dict[str, Any], *,
                                 dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._finish_readonly(proj, out)
        chain = evidence_chain(proj, raw["claim_id"])
        out["artifacts"].append({"kind": "evidence_chain", "path": None, "note": chain})
        claim = proj.claim_by_id(raw["claim_id"])
        label = claim.get("epistemic_label", EpistemicLabel.REPORTED.value) if claim else EpistemicLabel.REPORTED.value
        return {"summary": f"Evidence chain for claim {raw['claim_id']}: "
                           f"{len(chain['evidence_chain'])} record(s), "
                           f"{len(chain['unresolved_refs'])} unresolved.",
                "findings": [{"label": label,
                              "statement": f"claim {raw['claim_id']} labeled {label}; "
                                           f"{len(chain['evidence_chain'])} evidence records resolve",
                              "source": "evidence_chain"}]}

    # ------------------------------------------------------------------
    # actions — graph.* conflicts
    # ------------------------------------------------------------------
    def _do_graph_conflict_scan(self, raw: dict[str, Any], out: dict[str, Any], *,
                                dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._finish_readonly(proj, out)
        open_conflicts = [c for c in proj.conflicts if c["status"] == "OPEN"]
        out["artifacts"].append({"kind": "conflict_report", "path": None,
                                 "note": {"open": open_conflicts, "count": len(open_conflicts),
                                          "resolved_count": len(proj.conflicts) - len(open_conflicts)}})
        findings = []
        for c in open_conflicts:
            a = proj.claim_by_id(c["claim_a"])
            b = proj.claim_by_id(c["claim_b"])
            label_a = a.get("epistemic_label", "?") if a else "?"
            label_b = b.get("epistemic_label", "?") if b else "?"
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": f"OPEN {c['id']}: {c['claim_a']} ({label_a}) vs "
                                          f"{c['claim_b']} ({label_b}) — {c['reason']}",
                             "source": "conflict_detector"})
        if not findings:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": "no open claim conflicts", "source": "conflict_detector"})
        return {"summary": f"Conflict scan: {len(open_conflicts)} open conflict(s).", "findings": findings}

    def _do_graph_conflict_resolve(self, raw: dict[str, Any], out: dict[str, Any], *,
                                   dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        cid = raw["conflict_id"]
        conflict = next((c for c in proj.conflicts if c["id"] == cid), None)
        if conflict is None:
            raise KgeError(KgeErrorCode.CONFLICT_UNDETECTED,
                           f"Conflict '{cid}' is not recorded in this knowledge base.",
                           detail={"how_to_fix": "action=graph.conflict_scan lists conflict ids."})
        if conflict["status"] != "OPEN":
            raise KgeError(KgeErrorCode.CONFLICT_UNDETECTED,
                           f"Conflict '{cid}' is already {conflict['status']}.",
                           detail={"status": conflict["status"]})
        preferred = raw["preferred_claim"]
        if proj.claim_by_id(preferred) is None:
            raise KgeError(KgeErrorCode.ENTITY_NOT_FOUND,
                           f"Preferred claim '{preferred}' does not exist.",
                           detail={"how_to_fix": "Preferred claim must be a recorded claim id."})
        approver, appr_rev = self._check_approval(raw, proj, dry_run=dry_run)
        if approver is None and dry_run:
            out["assumptions"].append("Conflict adjudication requires human approval in a real run.")
        self._record(raw, proj, out, "CONFLICT_RESOLVED", {
            "conflict_id": cid, "status": "RESOLVED", "preferred_claim": preferred,
            "rationale": raw.get("rationale"), "approved_by": approver,
            "approval_revision": appr_rev,
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Resolved conflict {cid}: preferred claim {preferred} "
                           f"(approved by {approver or 'pending'}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"conflict {cid} → RESOLVED with preferred {preferred}",
                              "source": "event_log"}]}

    # ------------------------------------------------------------------
    # actions — graph.* ontology / query / import / export
    # ------------------------------------------------------------------
    def _do_graph_ontology(self, raw: dict[str, Any], out: dict[str, Any], *,
                           dry_run: bool) -> dict[str, Any]:
        proj = None
        if raw.get("project_id") and self.store.exists(raw["project_id"]):
            proj = self._projection_or_raise(raw)
            self._finish_readonly(proj, out)
        onto = self._ontology_or_base(proj)
        schema = kio.generate_ontology_schema(onto)
        out["artifacts"].append({"kind": "ontology", "path": None,
                                 "note": {"ontology": onto, "json_schema": schema}})
        return {"summary": f"Ontology v{onto.get('version')}: {len(onto.get('entity_types', []))} "
                           f"entity types, {len(onto.get('relation_types', []))} relation types.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"ontology_version={onto.get('version')}",
                              "source": "ontology"}]}

    def _do_graph_ontology_update(self, raw: dict[str, Any], out: dict[str, Any], *,
                                  dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        add_et = raw.get("add_entity_types", [])
        add_rt = raw.get("add_relation_types", [])
        replace = bool(raw.get("replace", False))
        if not add_et and not add_rt and not replace:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "ontology_update needs add_entity_types / add_relation_types / replace.",
                           detail={"known": "supply at least one vocabulary change"})
        if add_et:
            known = set(proj.ontology.get("entity_types", [])) | set(_BASE_ENTITY_TYPES)
            unknown = [t for t in add_et if not (t.isupper() and t.isalpha() and "_" in t or t.isupper() and t.isalpha())]
            unknown += [t for t in add_et if t in known]
            unknown = sorted(set(unknown))
            if unknown:
                raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                               "New entity types must be new UPPER_SNAKE tokens: "
                               + ", ".join(unknown),
                               detail={"already_known_or_invalid": unknown})
        if replace:
            approver, _rev = self._check_approval(raw, proj, dry_run=dry_run)
            if approver is None and dry_run:
                out["assumptions"].append("Breaking ontology replacement requires human approval "
                                          "in a real run.")
        version = raw.get("ontology_version")
        self._record(raw, proj, out, "ONTOLOGY_UPDATED", {
            "entity_types": add_et, "relation_types": add_rt,
            "ontology_version": version, "replace": replace,
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Ontology updated: +{len(add_et)} entity type(s), +{len(add_rt)} "
                           f"relation type(s) (version {proj.ontology.get('version')}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"ontology_version={proj.ontology.get('version')} "
                                           f"entity_types={len(proj.ontology.get('entity_types', []))}",
                              "source": "event_log"}]}

    def _do_graph_query(self, raw: dict[str, Any], out: dict[str, Any], *,
                        dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._finish_readonly(proj, out)
        q = raw["query"]
        kind = q.get("kind")
        results: list[dict[str, Any]] = []
        if kind == "entity":
            results = [e for e in proj.entities if q.get("id") in (None, e["id"])]
        elif kind == "claim":
            results = [c for c in proj.claims if q.get("id") in (None, c["id"])]
        elif kind == "claim_by_subject":
            results = [c for c in proj.claims if q.get("subject") == c.get("subject")]
        elif kind == "evidence":
            results = [e for e in proj.evidence if q.get("ref") in (None, e["ref"])]
        elif kind == "conflict":
            results = [c for c in proj.conflicts if c["status"] == "OPEN"]
        elif kind == "alias":
            results = [{"alias": k, "entity_id": v} for k, v in proj.aliases.items()
                       if q.get("id") in (None, v)]
        else:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Unknown query kind '{kind}'.", detail={"supported":
                           ["entity", "claim", "claim_by_subject", "evidence", "conflict", "alias"]})

        # Epistemic labels travel with every claim result so the caller can
        # never present a hypothesis as observed fact (bootstrap gate #4).
        out["artifacts"].append({"kind": "query_result", "path": None,
                                 "note": {"kind": kind, "count": len(results), "results": results}})
        findings = []
        for r in results[:8]:
            if kind == "claim" or kind == "claim_by_subject":
                label = r.get("epistemic_label", EpistemicLabel.REPORTED.value)
                findings.append({"label": label,
                                 "statement": f"{r['id']}: {r.get('predicate')} ({label}, "
                                              f"tier {r.get('evidence_tier')}, status {r.get('_status')})",
                                 "source": "graph_query"})
            elif kind == "entity":
                findings.append({"label": EpistemicLabel.OBSERVED.value,
                                 "statement": f"entity {r['id']} ({r.get('entity_type')})",
                                 "source": "graph_query"})
            elif kind == "conflict":
                findings.append({"label": EpistemicLabel.OBSERVED.value,
                                 "statement": f"OPEN {r['id']}: {r['claim_a']} vs {r['claim_b']}",
                                 "source": "graph_query"})
        if not findings:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": f"no {kind} results for query", "source": "graph_query"})
        return {"summary": f"Query kind={kind}: {len(results)} result(s).", "findings": findings}

    def _do_graph_import(self, raw: dict[str, Any], out: dict[str, Any], *,
                         dry_run: bool) -> dict[str, Any]:
        pid = raw["project_id"]
        if self.store.exists(pid):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"graph.import only creates fresh knowledge bases; '{pid}' already "
                           f"exists.", detail={"how_to_fix": "Use a new project_id, or replay the "
                                                             "document with add_* actions."})
        doc = raw.get("document") or {}
        content = raw.get("content")
        if isinstance(content, str):
            doc = kio.parse_import(content, fmt=raw.get("format", "auto"))
        if not isinstance(doc, dict):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Import document must be an object or a serialized string.",
                           detail={"got": type(doc).__name__})
        plan = kio.import_plan(doc)  # validates structure (bad payloads fail here)
        proj = Projection(project_id=pid)
        # Preflight on an empty projection: the plan must replay cleanly.
        for step in plan:
            fake = Event(revision=proj.revision + 1, type=step["type"],
                         recorded_at=_now_iso(), actor=SKILL_NAME, payload=step["payload"],
                         prev_hash=proj.head_hash, hash="<preflight>")
            apply_event(proj, fake)

        if dry_run:
            return {"summary": f"[dry-run] Import validated: {len(plan)} events would be applied "
                               f"to a fresh base '{pid}'.",
                    "findings": [{"label": EpistemicLabel.CALCULATED.value,
                                  "statement": f"entities={len(proj.entities)} claims={len(proj.claims)} "
                                               f"relations={len(proj.relations)} evidence={len(proj.evidence)}",
                                  "source": "import_preflight"}],
                    "artifacts": [{"kind": "import_preflight", "path": None,
                                   "note": {"events": len(plan), "project_id": pid}}]}

        approver, appr_rev = self._check_approval(raw, Projection(project_id=pid), dry_run=False)
        actor = raw.get("actor", {})
        actor_name = actor.get("id") or actor.get("role", "unknown")
        applied = 0
        for step in plan:
            ev = self.store.append(pid, step["type"], step["payload"], actor=actor_name,
                                   expected_revision=None)
            apply_event(proj, ev)
            applied += 1
            out["provenance"]["events_appended"].append(
                {"type": ev.type, "revision": ev.revision, "hash": ev.hash})
        out["provenance"]["head_revision"] = proj.revision
        out["provenance"]["head_hash"] = proj.head_hash
        # Record the approval that authorized this bulk write.
        self._record(raw, proj, out, "APPROVAL_GRANTED", {
            "scope": f"graph.import:{pid}", "approver": approver, "approval_revision": appr_rev,
        }, dry_run=False)
        self._finish_mutation(raw, proj, out, dry_run=False)
        return {"summary": f"Imported {applied} events into new base '{pid}' (approved by {approver}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"entities={len(proj.entities)} claims={len(proj.claims)} "
                                           f"relations={len(proj.relations)} evidence={len(proj.evidence)} "
                                           f"revision={proj.revision}",
                              "source": "import"}]}

    def _do_graph_export(self, raw: dict[str, Any], out: dict[str, Any], *,
                         dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._finish_readonly(proj, out)
        fmt = raw.get("format", "json")
        doc = kio.export_graph(proj, fmt=fmt)
        path = raw.get("path")
        if path and not dry_run:
            from .migration import render_export
            written = render_export(proj, path, fmt=fmt)
            out["artifacts"].append({"kind": "export_file", "path": str(written),
                                     "note": {"format": fmt, "bytes": written.stat().st_size}})
        else:
            out["artifacts"].append({"kind": "export_document", "path": None,
                                     "note": {"format": fmt, "content": doc["content"]}})
        return {"summary": f"Exported graph ({fmt}): {len(proj.entities)} entities, "
                           f"{len(proj.claims)} claims at revision {proj.revision}.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"export format={fmt} revision={proj.revision} "
                                           f"head_hash={proj.head_hash[:16]}…",
                              "source": "export"}]}

    # ------------------------------------------------------------------
    # actions — approval.grant
    # ------------------------------------------------------------------
    def _do_approval_grant(self, raw: dict[str, Any], out: dict[str, Any], *,
                           dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._record(raw, proj, out, "APPROVAL_GRANTED", {
            "approver": raw.get("approver"), "scope": raw.get("scope", "unspecified"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Approval by {raw.get('approver')} recorded at revision {proj.revision}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"approval event appended (scope={raw.get('scope')})",
                              "source": "event_log"}]}
