"""Service facade: the single entry the CLI and controller call.

Pipeline for every invocation:
  1. schema-validate input (OSM-E1xx)
  2. locate/rebuild the stream projection (OSM-E3xx)
  3. run the action (guards, OSM-E305/E306/E5xx)
  4. append events + refresh snapshot
  5. self-check: rebuild == snapshot (OSM-E702)
  6. schema-validate output (OSM-E701)

The facade owns the unified output envelope (spec §六): status, summary,
findings, assumptions, evidence_used, uncertainty, risks, artifacts,
requested_next_skills, validation, provenance, errors — always present, even
on failure, so the controller can always parse.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import rollback as rb
from . import watcher
from .errors import OsmError, OsmErrorCode
from .models import ActorRole, EpistemicLabel, EventType, MemoryTier, OutputStatus, ResearchState
from .recovery import recover, resume_plan
from .store import EventStore, Projection, apply_event
from .transition import check_transition, get_rule
from .validate import coerce_input_defaults, validate_input, validate_output

SKILL_NAME = "obsidian-state-manager"
SKILL_VERSION = "1.0.1"
CONTRACT_VERSION = "1.0"

# Actions that write long-term / verified knowledge and therefore require
# human approval regardless of transition guards (spec §七, §九.4).
_APPROVAL_GATED_ACTIONS = frozenset({"memory.promote"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StateManagerService:
    def __init__(self, store_root: str | Path, *, clock=None) -> None:
        self.store = EventStore(store_root, clock=clock)

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
                raise OsmError(
                    OsmErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    f"contract_version {raw.get('contract_version')!r} is not consumable by this "
                    f"build (supports 1.x). Migrate the payload or pin a compatible skill version.",
                    detail={"declared": raw.get("contract_version"), "supported": "1.x"},
                )
            action = raw["action"]
            handler = getattr(self, f"_do_{action.replace('.', '_').replace('-', '_')}", None)
            if handler is None:
                raise OsmError(
                    OsmErrorCode.INPUT_SCHEMA_VIOLATION,
                    f"Unknown action '{action}'.",
                    detail={"known_actions": sorted(self.actions())},
                )

            dry_run = bool(raw.get("dry_run", False))
            result = handler(raw, out, dry_run=dry_run)
            out.update(result)
            # Handlers never set status themselves; derive it from the error
            # list (envelope starts FAILED only as a safe default).
            if out.get("errors"):
                out["status"] = OutputStatus.PARTIAL.value
            else:
                out["status"] = OutputStatus.SUCCESS.value
        except OsmError as exc:
            self._apply_error(raw, out, exc)
        except Exception as exc:  # last-resort guard: never emit unparseable output
            self._apply_error(raw, out, OsmError(
                OsmErrorCode.TOOL_UNAVAILABLE,
                f"Unhandled internal error: {type(exc).__name__}: {exc}",
                detail={"exception_type": type(exc).__name__},
            ))

        out["provenance"]["completed_at"] = _now_iso()
        try:
            validate_output(out)
            out["validation"]["output_schema"] = "passed"
        except OsmError as exc:
            # Output-contract failure is itself reported through the envelope;
            # we never raise past handle().
            out["status"] = OutputStatus.FAILED.value
            out["validation"]["output_schema"] = "failed"
            out["errors"].append(exc.to_dict())
        return out

    @staticmethod
    def actions() -> list[str]:
        return [
            "project.init", "state.get", "state.transition", "state.rollback",
            "state.timeline", "state.diff", "evidence.attach", "evidence.retract",
            "hypothesis.record", "hypothesis.set_status", "decision.record",
            "task.checkpoint", "task.resume_plan", "memory.promote",
            "review.request", "review.complete", "approval.grant",
            "watcher.scan", "recovery.recover", "snapshot.verify", "project.list",
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

    def _apply_error(self, raw: dict[str, Any], out: dict[str, Any], exc: OsmError) -> None:
        status_map = {
            OsmErrorCode.APPROVAL_REQUIRED: OutputStatus.HUMAN_APPROVAL_REQUIRED,
            OsmErrorCode.APPROVAL_STALE: OutputStatus.HUMAN_APPROVAL_REQUIRED,
            OsmErrorCode.DOWNSTREAM_CAPABILITY_MISSING: OutputStatus.NEED_ADDITIONAL_SKILL,
            OsmErrorCode.MISSING_REQUIRED_FIELD: OutputStatus.BLOCKED,
            OsmErrorCode.INPUT_SCHEMA_VIOLATION: OutputStatus.BLOCKED,
            OsmErrorCode.EVIDENCE_UNVERIFIABLE: OutputStatus.BLOCKED,
            OsmErrorCode.PROJECT_NOT_FOUND: OutputStatus.BLOCKED,
            OsmErrorCode.TOOL_UNAVAILABLE: OutputStatus.FAILED,
            OsmErrorCode.STORE_IO_FAILURE: OutputStatus.FAILED,
        }
        out["status"] = status_map.get(exc.code, OutputStatus.FAILED).value
        out["errors"].append(exc.to_dict())
        out["summary"] = f"{exc.code.code}: {exc.message}"

    def _projection_or_raise(self, raw: dict[str, Any]) -> Projection:
        pid = raw["project_id"]
        if not self.store.exists(pid):
            raise OsmError(
                OsmErrorCode.PROJECT_NOT_FOUND,
                f"No state stream for project_id '{pid}'.",
                detail={"missing_field": "project stream",
                        "why_critical": "Every state action rebuilds from the project's event log; "
                                        "without a stream there is nothing to act on.",
                        "how_to_fix": "Run action=project.init once for this project_id."},
            )
        return self.store.rebuild(pid)

    def _record(self, raw: dict[str, Any], proj: Projection, out: dict[str, Any],
                event_type: EventType, payload: dict[str, Any], *, dry_run: bool) -> None:
        """Append one event (unless dry_run) and reflect it in the projection.

        Optimistic-concurrency (expected_revision) is enforced on BOTH paths:
        a dry-run that simulates against a stale view must fail exactly like a
        real write would, or dry-run would under-validate the request.
        """
        actor = raw.get("actor", {})
        actor_name = actor.get("id") or actor.get("role", "unknown")
        expected_revision = raw.get("expected_revision")
        if expected_revision is not None and expected_revision != proj.revision:
            raise OsmError(
                OsmErrorCode.INVALID_EVENT_SEQUENCE,
                f"Caller expected head revision {expected_revision} but stream head is "
                f"{proj.revision}; another session advanced the stream. Rebuild and retry.",
                detail={"expected": expected_revision, "actual_head": proj.revision,
                        "phase": "pre-flight"},
            )
        if dry_run:
            # Simulate: fold the event into the in-memory projection so later
            # logic (self-check, summary) sees the would-be state.
            from .store import Event
            fake = Event(revision=proj.revision + 1, type=event_type.value,
                         recorded_at=_now_iso(), actor=actor_name, payload=payload,
                         prev_hash=proj.head_hash, hash="<dry-run>")
            apply_event(proj, fake)
            out["provenance"]["events_appended"].append(
                {"type": event_type.value, "revision": "dry-run", "hash": "<dry-run>"})
            return
        ev = self.store.append(
            proj.project_id, event_type, payload,
            actor=actor_name,
            expected_revision=raw.get("expected_revision"),
        )
        apply_event(proj, ev)
        out["provenance"]["events_appended"].append(
            {"type": ev.type, "revision": ev.revision, "hash": ev.hash})
        out["provenance"]["head_revision"] = ev.revision
        out["provenance"]["head_hash"] = ev.hash

    def _finish_mutation(self, raw: dict[str, Any], proj: Projection,
                         out: dict[str, Any], *, dry_run: bool) -> None:
        """Snapshot + self-check after any mutating action (acceptance §八.4)."""
        out["state"] = proj.state.value
        if dry_run:
            out["validation"]["self_check"] = "skipped_dry_run"
            out["artifacts"].append({"kind": "projection", "path": None,
                                     "note": "dry-run: no snapshot written"})
            return
        snap_path = self.store.write_snapshot(proj.project_id, proj,
                                              actor=raw.get("actor", {}).get("id", SKILL_NAME))
        rebuilt = self.store.rebuild(proj.project_id)
        snap_on_disk = self.store.read_snapshot(proj.project_id)
        match = (rebuilt.to_snapshot()["head_hash"] == snap_on_disk["head_hash"]
                 and rebuilt.state.value == snap_on_disk["state"]
                 and rebuilt.revision == snap_on_disk["revision"])
        out["validation"]["rebuild_matches_snapshot"] = match
        out["validation"]["self_check"] = "passed" if match else "failed"
        if not match:
            raise OsmError(
                OsmErrorCode.SELF_CHECK_FAILED,
                "Post-write rebuild does not match the written snapshot; "
                "event log and snapshot disagree.",
                detail={"project_id": proj.project_id},
            )
        out["artifacts"].append({"kind": "snapshot", "path": str(snap_path)})

    def _state_view(self, proj: Projection) -> dict[str, Any]:
        live = [e for e in proj.evidence if not e.get("retracted")]
        return {
            "project_id": proj.project_id,
            "state": proj.state.value,
            "head_revision": proj.revision,
            "head_hash": proj.head_hash,
            "evidence_count": len(live),
            "evidence_retracted_count": len(proj.evidence) - len(live),
            "hypotheses": [{"id": h["id"], "status": h["status"]} for h in proj.hypotheses],
            "decisions_count": len(proj.decisions),
            "checkpoints": [{"task_id": c["task_id"], "state": c["state"]} for c in proj.checkpoints],
            "reviews": proj.reviews,
            "memory_tiers": {k: len(v) for k, v in proj.memory.items()},
            "metadata": proj.metadata,
        }

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _do_project_init(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        pid = raw["project_id"]
        if self.store.exists(pid):
            raise OsmError(OsmErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Project '{pid}' already has a state stream; init is once-only.",
                           detail={"how_to_fix": "Use action=state.get to inspect, or a new project_id."})
        proj = Projection(project_id=pid)
        self._record(raw, proj, out, EventType.PROJECT_INITIALIZED, {
            "title": raw.get("title"),
            "request": raw["request"],
            "constraints": raw.get("constraints", []),
            "context": raw.get("context", {}),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Initialized research stream '{pid}' in state OPEN.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"Stream created with head revision {out['provenance']['head_revision'] or 'dry-run'}.",
                              "source": "event_log"}]}

    def _do_project_list(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        projects = self.store.list_projects()
        views = []
        for pid in projects:
            try:
                views.append({"project_id": pid, "state": self.store.rebuild(pid).state.value})
            except OsmError as exc:
                views.append({"project_id": pid, "state": None, "error": exc.code.code})
        out["state"] = None
        return {"summary": f"{len(projects)} project stream(s) in store.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"Streams: {views}",
                              "source": "store_scan"}],
                "artifacts": []}

    def _do_state_get(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        out["state"] = proj.state.value
        view = self._state_view(proj)
        out["artifacts"].append({"kind": "state_view", "path": None, "note": view})
        return {"summary": f"Project '{proj.project_id}' is in state {proj.state.value} "
                           f"at revision {proj.revision}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"state={proj.state.value} revision={proj.revision} "
                                           f"evidence={view['evidence_count']} "
                                           f"hypotheses={len(view['hypotheses'])}",
                              "source": "event_log_rebuild"}]}

    def _do_state_transition(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        target = ResearchState(raw["to_state"])
        actor = raw.get("actor", {})
        role = ActorRole(actor.get("role", "skill"))
        approval = raw.get("human_approval_state")

        requested = {
            "from_state": proj.state.value, "to_state": target.value,
            "reason": raw.get("reason"), "actor": actor.get("id", role.value),
        }
        try:
            rule = check_transition(
                proj.state, target,
                projection=proj.guard_view(), approval=approval,
                actor_role=role, stream_revision=proj.revision,
            )
        except OsmError as exc:
            # Rejections are first-class audit records (spec §四.3: no silent loss).
            if not dry_run and exc.code in (OsmErrorCode.TRANSITION_REJECTED,
                                            OsmErrorCode.GUARD_UNSATISFIED):
                self._record(raw, proj, out, EventType.STATE_TRANSITION_REJECTED,
                             {**requested, "error": exc.to_dict()}, dry_run=False)
                self._finish_mutation(raw, proj, out, dry_run=False)
            raise

        self._record(raw, proj, out, EventType.STATE_TRANSITION_REQUESTED,
                     requested, dry_run=dry_run)
        self._record(raw, proj, out, EventType.STATE_TRANSITIONED,
                     {**requested, "guard_note": rule.note,
                      "irreversible": rule.irreversible}, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        prefix = "[dry-run] " if dry_run else ""
        return {"summary": f"{prefix}Transitioned {requested['from_state']} → {target.value}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"state={proj.state.value} after guard pass ({rule.note or 'no note'})",
                              "source": "transition_engine"}]}

    def _do_state_rollback(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        target = ResearchState(raw["to_state"])
        approval = raw.get("human_approval_state")
        # Trust boundary: approval must be a RECORDED APPROVAL_GRANTED event,
        # not a self-declared payload field (same rule as transition guards).
        recorded = proj.approvals
        if not any(a.get("revision") is not None and a["revision"] <= proj.revision
                   for a in recorded):
            raise OsmError(OsmErrorCode.APPROVAL_REQUIRED,
                           "Rollback rewrites the working baseline (compensating event); it requires "
                           "a RECORDED APPROVAL_GRANTED event before the current head.",
                           detail={"how_to_fix": "Emit action=approval.grant for this scope first.",
                                   "recorded_approvals": [
                                       {"revision": a.get("revision"), "scope": a.get("scope")}
                                       for a in recorded]})
        if not (approval and approval.get("granted")):
            raise OsmError(OsmErrorCode.APPROVAL_REQUIRED,
                           "Rollback requires the caller to re-affirm approval for the compensating "
                           "event.",
                           detail={"how_to_fix": "human_approval_state.granted=true with approver id."})
        rb.check_rollback(proj, target)
        before = proj.to_snapshot()
        self._record(raw, proj, out, EventType.DOWNGRADE_TRIGGERED, {
            "kind": "rollback",
            "from_state": before["state"], "to_state": target.value,
            "reason": raw.get("reason"),
            "approved_by": approval.get("approver"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        diff = rb.diff_snapshots(before, proj.to_snapshot())
        return {"summary": f"Rolled back {before['state']} → {target.value} via compensating event "
                           f"(history preserved).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"rollback applied; diff counts={diff['counts']}",
                              "source": "event_log"}],
                "artifacts": out["artifacts"] + [{"kind": "rollback_diff", "path": None, "note": diff}]}

    def _do_state_timeline(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        events = self.store.read_events(proj.project_id)
        human = []
        machine = []
        for ev in events:
            line = f"r{ev.revision:>4} {ev.recorded_at} {ev.type:<28} {ev.actor}"
            detail = ""
            if ev.type == EventType.STATE_TRANSITIONED.value:
                detail = f"{ev.payload.get('from_state')} → {ev.payload.get('to_state')}"
            elif ev.type == EventType.STATE_TRANSITION_REJECTED.value:
                detail = f"REJECTED {ev.payload.get('from_state')} → {ev.payload.get('to_state')}"
            elif ev.type == EventType.EVIDENCE_ATTACHED.value:
                detail = ev.payload.get("ref", "")
            elif ev.type == EventType.DOWNGRADE_TRIGGERED.value:
                detail = f"{ev.payload.get('from_state')} → {ev.payload.get('to_state')} ({ev.payload.get('kind')})"
            human.append(f"{line}  {detail}".rstrip())
            machine.append({"revision": ev.revision, "type": ev.type, "at": ev.recorded_at,
                            "actor": ev.actor, "summary": detail, "hash": ev.hash})
        out["state"] = proj.state.value
        out["artifacts"].append({"kind": "timeline_human", "path": None, "note": "\n".join(human)})
        out["artifacts"].append({"kind": "timeline_machine", "path": None, "note": machine})
        return {"summary": f"Timeline for '{proj.project_id}': {len(events)} events, "
                           f"current state {proj.state.value}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"{len(events)} events replayed; head r{proj.revision}",
                              "source": "event_log"}]}

    def _do_state_diff(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        snap = self.store.read_snapshot(proj.project_id)
        live = proj.to_snapshot()
        diff = rb.diff_snapshots(
            {k: v for k, v in snap.items() if k not in ("written_at", "written_by")},
            live,
        )
        out["state"] = proj.state.value
        out["artifacts"].append({"kind": "snapshot_vs_live_diff", "path": None, "note": diff})
        same = diff["counts"] == {"added": 0, "removed": 0, "changed": 0}
        return {"summary": "Snapshot and live rebuild agree." if same else
                           f"Snapshot/live divergence: {diff['counts']}.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"diff counts={diff['counts']}",
                              "source": "diff_engine"}],
                "validation": {**out["validation"], "rebuild_matches_snapshot": same,
                               "self_check": "passed" if same else "failed"}}

    def _do_evidence_attach(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        evd = raw["evidence"]
        if evd.get("tier") == MemoryTier.VERIFIED.value:
            approval = raw.get("human_approval_state")
            if not (approval and approval.get("granted")):
                raise OsmError(OsmErrorCode.APPROVAL_REQUIRED,
                               "Attaching evidence directly into the verified_knowledge tier requires "
                               "human approval; otherwise attach to unreviewed_draft and promote later.",
                               detail={"how_to_fix": "Use tier=unreviewed_draft, or obtain approval."})
        self._record(raw, proj, out, EventType.EVIDENCE_ATTACHED, {
            "ref": evd["ref"],
            "sha256": evd.get("sha256"),
            "tier": evd.get("tier", MemoryTier.DRAFT.value),
            "summary": evd.get("summary"),
            "review_by": evd.get("review_by"),
            "contradicts_hypothesis": evd.get("contradicts_hypothesis"),
        }, dry_run=dry_run)

        # Contradiction wiring: attaching evidence flagged as contradicting a
        # hypothesis marks that hypothesis CONTESTED in the same commit.
        contradicted: list[str] = []
        for hid in evd.get("contradicts_hypothesis") or []:
            if any(h["id"] == hid for h in proj.hypotheses):
                self._record(raw, proj, out, EventType.HYPOTHESIS_STATUS_CHANGED, {
                    "id": hid, "to_status": "CONTESTED",
                    "reason": f"contradicted by evidence {evd['ref']}",
                }, dry_run=dry_run)
                contradicted.append(hid)

        auto_downgrade: dict[str, Any] | None = None
        scan = watcher.scan(proj)
        if raw.get("auto_downgrade", True) and scan["proposals"]:
            proposal = scan["proposals"][0]
            target = ResearchState(proposal["to_state"])
            rule = get_rule(proj.state, target)
            if rule is not None:
                self._record(raw, proj, out, EventType.DOWNGRADE_TRIGGERED, {
                    "kind": proposal["kind"],
                    "from_state": proj.state.value,
                    "to_state": target.value,
                    "reason": proposal["reason"],
                }, dry_run=dry_run)
                auto_downgrade = proposal

        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        findings = [{"label": EpistemicLabel.OBSERVED.value,
                     "statement": f"evidence {evd['ref']} attached to tier "
                                  f"{evd.get('tier', MemoryTier.DRAFT.value)}",
                     "source": "event_log"}]
        if contradicted:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": f"hypotheses marked CONTESTED: {contradicted}",
                             "source": "contradiction_wiring"})
        if auto_downgrade:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": f"auto-downgrade applied: {auto_downgrade['from_state']} → "
                                          f"{auto_downgrade['to_state']} ({auto_downgrade['reason']})",
                             "source": "watcher"})
        summary = f"Attached evidence {evd['ref']}."
        if auto_downgrade:
            summary += f" Contradiction forced state {auto_downgrade['from_state']} → {auto_downgrade['to_state']}."
        return {"summary": summary, "findings": findings,
                "risks": [{"label": EpistemicLabel.INFERRED.value,
                           "statement": f"state now {proj.state.value}; forward guards re-evaluated on next transition"}]
                          if auto_downgrade else []}

    def _do_evidence_retract(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        ref = raw["ref"]
        if not any(e["ref"] == ref and not e.get("retracted") for e in proj.evidence):
            raise OsmError(OsmErrorCode.EVIDENCE_UNVERIFIABLE,
                           f"No live evidence with ref '{ref}' to retract.",
                           detail={"how_to_fix": "action=state.get lists live evidence refs."})
        self._record(raw, proj, out, EventType.EVIDENCE_RETRACTED,
                     {"ref": ref, "reason": raw.get("reason")}, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Retracted evidence {ref}; retained in log as retracted (not deleted).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"evidence {ref} retracted at revision {proj.revision}",
                              "source": "event_log"}]}

    def _do_hypothesis_record(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        hyp = raw["hypothesis"]
        if any(h["id"] == hyp["id"] for h in proj.hypotheses):
            raise OsmError(OsmErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"Hypothesis id '{hyp['id']}' already exists; use hypothesis.set_status.")
        self._record(raw, proj, out, EventType.HYPOTHESIS_RECORDED, {
            "id": hyp["id"], "statement": hyp["statement"],
            "status": "PROPOSED",
            "supporting_evidence": hyp.get("supporting_evidence", []),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Recorded hypothesis {hyp['id']} as PROPOSED.",
                "findings": [{"label": EpistemicLabel.HYPOTHESIS.value,
                              "statement": hyp["statement"],
                              "source": f"hypothesis:{hyp['id']}"}]}

    def _do_hypothesis_set_status(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        hid, to_status = raw["id"], raw["to_status"]
        if not any(h["id"] == hid for h in proj.hypotheses):
            raise OsmError(OsmErrorCode.EVIDENCE_UNVERIFIABLE,
                           f"Unknown hypothesis id '{hid}'.",
                           detail={"how_to_fix": "action=state.get lists hypothesis ids."})
        self._record(raw, proj, out, EventType.HYPOTHESIS_STATUS_CHANGED, {
            "id": hid, "to_status": to_status, "reason": raw.get("reason"),
        }, dry_run=dry_run)

        auto_downgrade = None
        if to_status == "CONTESTED" and raw.get("auto_downgrade", True):
            scan = watcher.scan(proj)
            if scan["proposals"]:
                proposal = scan["proposals"][0]
                target = ResearchState(proposal["to_state"])
                if get_rule(proj.state, target) is not None:
                    self._record(raw, proj, out, EventType.DOWNGRADE_TRIGGERED, {
                        "kind": proposal["kind"], "from_state": proj.state.value,
                        "to_state": target.value, "reason": proposal["reason"],
                    }, dry_run=dry_run)
                    auto_downgrade = proposal

        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        summary = f"Hypothesis {hid} → {to_status}."
        if auto_downgrade:
            summary += (f" Contradiction downgraded state {auto_downgrade['from_state']} → "
                        f"{auto_downgrade['to_state']}.")
        return {"summary": summary,
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"hypothesis {hid} status={to_status}; state={proj.state.value}",
                              "source": "event_log"}]}

    def _do_decision_record(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        dec = raw["decision"]
        self._record(raw, proj, out, EventType.DECISION_RECORDED, {
            "id": dec["id"], "decision": dec["decision"],
            "rationale": dec.get("rationale"),
            "alternatives": dec.get("alternatives", []),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Decision {dec['id']} recorded.",
                "findings": [{"label": EpistemicLabel.REPORTED.value,
                              "statement": dec["decision"],
                              "source": f"decision:{dec['id']}"}]}

    def _do_task_checkpoint(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        completed = raw.get("completed_work", [])
        pending = raw.get("pending_work", [])
        self._record(raw, proj, out, EventType.TASK_CHECKPOINT, {
            "task_id": raw["task_id"], "state": proj.state.value,
            "completed_work": completed, "pending_work": pending,
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Checkpoint for task '{raw['task_id']}' in state {proj.state.value}: "
                           f"{len(completed)} done / {len(pending)} pending.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"checkpoint revision {proj.revision}",
                              "source": "event_log"}]}

    def _do_task_resume_plan(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        plan = resume_plan(self.store, raw["project_id"], raw["task_id"],
                           raw.get("candidate_work", []))
        out["state"] = plan["current_state"]
        out["artifacts"].append({"kind": "resume_plan", "path": None, "note": plan})
        return {"summary": f"Resume plan for task '{raw['task_id']}': {len(plan['to_run'])} to run, "
                           f"{plan['skipped_count']} already done (will not be re-executed).",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": f"to_run={len(plan['to_run'])} skipped={plan['skipped_count']} "
                                           f"recovery_status={plan['recovery_status']}",
                              "source": "resume_planner"}]}

    def _do_memory_promote(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        approval = raw.get("human_approval_state")
        to_tier = raw["to_tier"]
        if to_tier in (MemoryTier.VERIFIED.value, MemoryTier.PROJECT.value):
            if not (approval and approval.get("granted")):
                raise OsmError(OsmErrorCode.APPROVAL_REQUIRED,
                               f"Promotion into tier '{to_tier}' writes long-term knowledge and requires "
                               "explicit human approval (acceptance §九.4).",
                               detail={"how_to_fix": "human_approval_state.granted=true with approver + revision."})
        self._record(raw, proj, out, EventType.MEMORY_PROMOTED, {
            "ref": raw["ref"], "to_tier": to_tier,
            "approved_by": approval.get("approver") if approval else None,
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Promoted {raw['ref']} into tier {to_tier} (versioned at revision {proj.revision}).",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"tier {to_tier} now holds {len(proj.memory.get(to_tier, []))} item(s)",
                              "source": "event_log"}]}

    def _do_review_request(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._record(raw, proj, out, EventType.REVIEW_REQUESTED,
                     {"scope": raw.get("scope", "state"), "requested_by": raw.get("actor", {}).get("id")},
                     dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": "Review requested.",
                "requested_next_skills": raw.get("suggest_skills") or [
                    {"skill": "obsidian-red-team", "reason": "independent adversarial review",
                     "inputs_needed": ["snapshot", "timeline"]}]}

    def _do_review_complete(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        verdict = raw["verdict"]
        self._record(raw, proj, out, EventType.REVIEW_COMPLETED, {
            "verdict": verdict, "reviewer": raw.get("reviewer"), "notes": raw.get("notes"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Review completed with verdict '{verdict}'.",
                "findings": [{"label": EpistemicLabel.REPORTED.value,
                              "statement": f"verdict={verdict} by {raw.get('reviewer', 'unknown')}",
                              "source": "review_record"}]}

    def _do_approval_grant(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        self._record(raw, proj, out, EventType.APPROVAL_GRANTED, {
            "approver": raw.get("approver"), "scope": raw.get("scope", "unspecified"),
        }, dry_run=dry_run)
        self._finish_mutation(raw, proj, out, dry_run=dry_run)
        return {"summary": f"Approval by {raw.get('approver')} recorded at revision {proj.revision}.",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": "approval event appended",
                              "source": "event_log"}]}

    def _do_watcher_scan(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        result = watcher.scan(proj)
        out["state"] = proj.state.value
        out["artifacts"].append({"kind": "watcher_report", "path": None, "note": result})
        findings = []
        for s in result["stale_evidence"]:
            findings.append({"label": EpistemicLabel.CALCULATED.value,
                             "statement": f"evidence {s['ref']} past review_by {s['review_by']}",
                             "source": "watcher:staleness"})
        for p in result["proposals"]:
            findings.append({"label": EpistemicLabel.RECOMMENDATION.value,
                             "statement": f"propose {p['kind']}: {p['from_state']} → {p['to_state']} ({p['reason']})",
                             "source": "watcher"})
        if not findings:
            findings.append({"label": EpistemicLabel.OBSERVED.value,
                             "statement": "no stale evidence, no contested hypotheses",
                             "source": "watcher"})
        return {"summary": f"Watcher scan: {len(result['stale_evidence'])} stale, "
                           f"{len(result['contested_hypotheses'])} contested, "
                           f"{len(result['proposals'])} proposal(s).",
                "findings": findings}

    def _do_recovery_recover(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        rec = recover(self.store, raw["project_id"])
        out["state"] = rec["current_state"]
        out["artifacts"].append({"kind": "recovery_report", "path": None, "note": rec})
        proj = self._projection_or_raise(raw)
        if rec["status"] != "CLEAN":
            # Refresh the snapshot so subsequent runs start CLEAN.
            if not dry_run:
                self.store.write_snapshot(proj.project_id, proj,
                                          actor=raw.get("actor", {}).get("id", SKILL_NAME))
                self._record(raw, proj, out, EventType.RECOVERY_PERFORMED, {
                    "status": rec["status"], "head_revision": proj.revision,
                }, dry_run=False)
                self._finish_mutation(raw, proj, out, dry_run=False)
        return {"summary": f"Recovery status {rec['status']}; state {rec['current_state']} "
                           f"at revision {rec['head_revision']}. Guidance: {rec['guidance']}",
                "findings": [{"label": EpistemicLabel.OBSERVED.value,
                              "statement": f"recovery_status={rec['status']}",
                              "source": "recovery_engine"}]}

    def _do_snapshot_verify(self, raw: dict[str, Any], out: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        proj = self._projection_or_raise(raw)
        snap = self.store.read_snapshot(proj.project_id)
        rebuilt = proj.to_snapshot()
        match = (snap.get("head_hash") == rebuilt["head_hash"]
                 and snap.get("state") == rebuilt["state"]
                 and snap.get("revision") == rebuilt["revision"])
        out["state"] = proj.state.value
        out["validation"]["rebuild_matches_snapshot"] = match
        out["validation"]["self_check"] = "passed" if match else "failed"
        if not match:
            raise OsmError(OsmErrorCode.SELF_CHECK_FAILED,
                           "Snapshot disagrees with event-log rebuild.",
                           detail={"snapshot_revision": snap.get("revision"),
                                   "rebuild_revision": rebuilt["revision"]})
        return {"summary": f"Snapshot consistent with event log at revision {proj.revision}.",
                "findings": [{"label": EpistemicLabel.CALCULATED.value,
                              "statement": "rebuild == snapshot (head_hash, state, revision)",
                              "source": "self_check"}]}
