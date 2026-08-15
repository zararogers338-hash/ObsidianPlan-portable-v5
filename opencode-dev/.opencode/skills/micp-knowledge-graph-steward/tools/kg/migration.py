"""Migration and schema-evolution support (spec §四.7, §九.4, §十一.3).

`compute_migration` is the single migration decision function: it reads a
store's layout_version and ontology version and decides whether a migration
step is required, can be skipped, or is unsupported. `migrate_store` performs
a monotonic layout upgrade by rewriting the store in place and appending a
MIGRATION event so the chain stays audit-trail-complete.

Schema-version policy (spec §十一.3):
  - Breaking input/output contract change -> major bump of skill version.
  - New optional fields -> minor bump.
  - Implementation fix without contract change -> patch bump.
  - Outputs written under an older major contract are migrated by an explicit
    migration step or rejected (KGE-E801/E802); never silently reinterpreted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import STORE_LAYOUT_VERSION, KnowledgeStore, Projection
from .errors import KgeError, KgeErrorCode


def compute_migration(store: KnowledgeStore, project_id: str) -> dict[str, Any]:
    """Decide whether migration is required for a store.

    Returns:
      {"required": bool, "reason": str, "store_layout": int, "current_layout": int}
    """
    stream = store.stream_dir(project_id)
    snapshot_path = stream / "snapshot.json"
    store_layout = STORE_LAYOUT_VERSION
    if snapshot_path.is_file():
        snap = store.read_snapshot(project_id)
        store_layout = int(snap.get("layout_version", 1))
    if store_layout == STORE_LAYOUT_VERSION:
        return {"required": False, "reason": "layout current",
                "store_layout": store_layout, "current_layout": STORE_LAYOUT_VERSION}
    if store_layout > STORE_LAYOUT_VERSION:
        raise KgeError(KgeErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                       f"Store layout {store_layout} is newer than this build "
                       f"({STORE_LAYOUT_VERSION}); refusing to downgrade.",
                       detail={"store_layout": store_layout,
                               "current_layout": STORE_LAYOUT_VERSION})
    return {"required": True, "reason": f"layout {store_layout} < {STORE_LAYOUT_VERSION}",
            "store_layout": store_layout, "current_layout": STORE_LAYOUT_VERSION}


def migrate_store(store: KnowledgeStore, project_id: str, *, actor: str,
                  dry_run: bool = False) -> dict[str, Any]:
    """Migrate a store forward in place (layout N -> current).

    Conservative: no data rewriting — the current layout only adds metadata.
    If future layouts need structural rewrites, the migration table grows
    here; each entry must be monotonic and reversible via backup.
    """
    decision = compute_migration(store, project_id)
    if not decision["required"]:
        return {"migrated": False, "decision": decision, "events_appended": []}
    if dry_run:
        return {"migrated": True, "decision": decision, "dry_run": True,
                "events_appended": []}
    events = store.read_events(project_id)
    proj = Projection(project_id=project_id)
    # Rebuild in memory so the migration event lands on a correct chain head.
    from .store import apply_event
    for ev in events:
        apply_event(proj, ev)
    ev = store.append(project_id, "MIGRATION_PERFORMED", {
        "from_layout": decision["store_layout"],
        "to_layout": STORE_LAYOUT_VERSION,
        "reason": decision["reason"],
    }, actor=actor, expected_revision=proj.revision)
    store.write_snapshot(project_id, proj, actor=actor)
    return {"migrated": True, "decision": decision,
            "events_appended": [{"type": ev.type, "revision": ev.revision, "hash": ev.hash}]}


def render_export(proj: Any, path: str | Path, *, fmt: str = "json") -> Path:
    """Write a graph export to a file; returns the file path."""
    from .io import export_graph

    doc = export_graph(proj, fmt=fmt)
    content = doc["content"]
    if isinstance(content, str):
        content = content.encode("utf-8")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return out
