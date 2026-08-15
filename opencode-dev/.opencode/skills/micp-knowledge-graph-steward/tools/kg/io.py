"""Schema generation, import/export, and graph dumps (spec §五.1, §五.2).

Pure and deterministic. YAML export/import works only when PyYAML is
installed; JSON always works. Import validation reuses the store's apply_event
pipeline through a dry-run projection so bad payloads fail before any write.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import KgeError, KgeErrorCode

try:  # pragma: no cover - environment dependent
    import yaml as _yaml

    _HAVE_YAML = True
except Exception:  # pragma: no cover
    _yaml = None
    _HAVE_YAML = False

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

_BASE_CLAIM_KINDS = ["IDENTITY", "TYPE", "SYNONYM", "VALUE", "OBSERVATION", "CAUSAL", "NORMATIVE"]
_BASE_TIERS = ["EXTERNAL_REPORTED", "INTERNAL_OBSERVED", "CALCULATED", "INFERRED",
               "HYPOTHESIS", "VALIDATED"]
_BASE_LABELS = ["OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"]


def base_ontology() -> dict[str, Any]:
    """The default MICP ontology shipped with the skill (spec §四.1)."""
    return {
        "entity_types": list(_BASE_ENTITY_TYPES),
        "relation_types": list(_BASE_RELATION_TYPES),
        "claim_kinds": list(_BASE_CLAIM_KINDS),
        "evidence_tiers": list(_BASE_TIERS),
        "epistemic_labels": list(_BASE_LABELS),
        "version": 1,
    }


def generate_ontology_schema(ontology: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a JSON-Schema describing the entity/relation/claim vocabulary.

    This is a real tool (spec §五.1): it consumes an ontology (default the
    base ontology) and produces a draft-07 schema that `graph.validate_*
    against_ontology` uses to type-check knowledge items at write time.
    """
    onto = ontology or base_ontology()
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://obsidian.panshi/skills/micp-knowledge-graph-steward/ontology.schema.json",
        "title": "MICP Knowledge Graph ontology contract",
        "description": "Machine-readable ontology vocabulary for the MICP knowledge graph.",
        "ontology_version": int(onto.get("version", 1)),
        "entity_types": list(onto.get("entity_types", _BASE_ENTITY_TYPES)),
        "relation_types": list(onto.get("relation_types", _BASE_RELATION_TYPES)),
        "claim_kinds": list(onto.get("claim_kinds", _BASE_CLAIM_KINDS)),
        "evidence_tiers": list(onto.get("evidence_tiers", _BASE_TIERS)),
        "epistemic_labels": list(onto.get("epistemic_labels", _BASE_LABELS)),
    }


def validate_against_ontology(item: dict[str, Any], ontology_schema: dict[str, Any],
                              *, kind: str) -> list[str]:
    """Type-check a knowledge item against the ontology schema. Returns a list
    of human-readable violations (empty when valid)."""
    violations: list[str] = []
    if kind == "entity":
        et = item.get("entity_type")
        if et not in ontology_schema.get("entity_types", []):
            violations.append(f"entity_type '{et}' is not in the ontology")
    elif kind == "relation":
        rt = item.get("relation_type")
        if rt not in ontology_schema.get("relation_types", []):
            violations.append(f"relation_type '{rt}' is not in the ontology")
        for endpoint in ("from_id", "to_id"):
            if not item.get(endpoint):
                violations.append(f"relation missing '{endpoint}'")
    elif kind == "claim":
        ck = item.get("claim_kind")
        if ck not in ontology_schema.get("claim_kinds", []):
            violations.append(f"claim_kind '{ck}' is not in the ontology")
        tier = item.get("evidence_tier")
        if tier not in ontology_schema.get("evidence_tiers", []):
            violations.append(f"evidence_tier '{tier}' is not in the ontology")
        label = item.get("epistemic_label")
        if label not in ontology_schema.get("epistemic_labels", []):
            violations.append(f"epistemic_label '{label}' is not in the ontology")
    return violations


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------

def export_graph(proj: Any, *, fmt: str = "json") -> dict[str, Any]:
    """Serialize a projection into a portable graph document (spec §五.2)."""
    document = {
        "project_id": proj.project_id,
        "export_version": 1,
        "revision": proj.revision,
        "head_hash": proj.head_hash,
        "ontology": proj.ontology,
        "entities": proj.entities,
        "relations": proj.relations,
        "claims": proj.claims,
        "evidence": proj.evidence,
        "conflicts": proj.conflicts,
        "aliases": proj.aliases,
    }
    if fmt == "yaml":
        if not _HAVE_YAML:
            raise KgeError(KgeErrorCode.TOOL_UNAVAILABLE,
                           "PyYAML is not installed; YAML export unavailable. Use fmt=json.",
                           detail={"how_to_fix": "pip install pyyaml, or request fmt=json"})
        return {"format": "yaml", "content": _yaml.safe_dump(document, sort_keys=False)}
    if fmt != "json":
        raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                       f"Unknown export format '{fmt}'. Supported: json, yaml.",
                       detail={"supported": ["json", "yaml"]})
    return {"format": "json", "content": json.dumps(document, ensure_ascii=False, indent=2)}


def parse_import(payload: str, *, fmt: str = "auto") -> dict[str, Any]:
    """Parse an import document (JSON or YAML). Returns the graph document dict."""
    if fmt == "auto":
        stripped = payload.lstrip()
        fmt = "yaml" if stripped.startswith(("{", "[")) is False and "\n" in stripped else "json"
        if stripped.startswith(("{", "[")):
            fmt = "json"
        else:
            fmt = "yaml"
    if fmt == "yaml":
        if not _HAVE_YAML:
            raise KgeError(KgeErrorCode.TOOL_UNAVAILABLE,
                           "PyYAML is not installed; YAML import unavailable. Use fmt=json.",
                           detail={"how_to_fix": "pip install pyyaml, or request fmt=json"})
        try:
            return _yaml.safe_load(payload)
        except Exception as exc:
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           f"YAML parse failed: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                       f"JSON parse failed: {exc.msg} at line {exc.lineno}") from exc


def import_plan(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a graph document into an ordered list of write operations.

    Returns a list of {"type": <event type>, "payload": {...}} which the
    service replays onto a fresh store. Validation happens here (structural
    integrity of the document) so a corrupt import never reaches the store.
    """
    plan: list[dict[str, Any]] = []
    if not isinstance(doc, dict):
        raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                       "Import document must be an object.", detail={"got": type(doc).__name__})

    ontology = doc.get("ontology")
    if not isinstance(ontology, dict) or not ontology.get("entity_types"):
        raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                       "Import document missing a valid 'ontology' with entity_types.",
                       detail={"keys": sorted(doc.keys())})

    plan.append({"type": "KB_INITIALIZED", "payload": {
        "title": doc.get("title", "imported"),
        "request": "import",
        "entity_types": ontology.get("entity_types", []),
        "relation_types": ontology.get("relation_types", []),
        "ontology_version": int(ontology.get("version", 1)),
    }})

    for alias, eid in (doc.get("aliases") or {}).items():
        plan.append({"type": "ENTITY_UPSERTED", "payload": {"entity": {
            "id": eid, "entity_type": "UNKNOWN", "canonical_name": alias},
            "aliases": [alias]}})

    for ent in doc.get("entities", []):
        if not isinstance(ent, dict) or not ent.get("id"):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Import entity missing 'id'.", detail={"entity": ent})
        plan.append({"type": "ENTITY_UPSERTED", "payload": {
            "entity": ent, "aliases": ent.get("aliases", [])}})

    for rel in doc.get("relations", []):
        if not isinstance(rel, dict) or not (rel.get("from_id") and rel.get("to_id")):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Import relation missing endpoints.", detail={"relation": rel})
        plan.append({"type": "RELATION_ADDED", "payload": {"relation": rel}})

    for claim in doc.get("claims", []):
        if not isinstance(claim, dict) or not claim.get("id"):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Import claim missing 'id'.", detail={"claim": claim})
        plan.append({"type": "CLAIM_ADDED", "payload": {"claim": claim}})

    for ev in doc.get("evidence", []):
        if not isinstance(ev, dict) or not ev.get("ref"):
            raise KgeError(KgeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "Import evidence missing 'ref'.", detail={"evidence": ev})
        plan.append({"type": "EVIDENCE_REGISTERED", "payload": {
            "ref": ev["ref"], "sha256": ev.get("sha256"), "tier": ev.get("tier"),
            "source": ev.get("source"), "summary": ev.get("summary")}})
    return plan
