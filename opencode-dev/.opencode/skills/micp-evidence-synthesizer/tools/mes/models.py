"""Shared domain constants and envelope helpers for MES."""

from __future__ import annotations

import hashlib
import json
from enum import Enum

SKILL_NAME = "micp-evidence-synthesizer"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0"

LABELS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")
LAYERS = (
    "biological",
    "chemical",
    "mineral_phase",
    "porous_media",
    "engineering_performance",
    "environmental_impact",
    "other",
)
EVIDENCE_LEVELS = ("L1_direct_observation", "L2_strong_indirect", "L3_weak_indirect", "L4_no_evidence", "expert_opinion")
RISK_OF_BIAS_LEVELS = ("low", "moderate", "high", "critical", "unclear")
STATUSES = (
    "SUCCESS",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "NEED_ADDITIONAL_SKILL",
    "HUMAN_APPROVAL_REQUIRED",
)


class OutputStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


def stable_digest(*objects) -> str:
    """Deterministic sha256 over JSON-canonicalized inputs (audit anchor)."""
    h = hashlib.sha256()
    for obj in objects:
        raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        h.update(raw.encode("utf-8"))
    return h.hexdigest()


def new_envelope(action, task_id, project_id, skill_version=SKILL_VERSION,
                 contract_version=CONTRACT_VERSION, started_at=None) -> dict:
    """A blank, contract-shaped output envelope (all required fields present)."""
    return {
        "contract_version": contract_version,
        "skill": SKILL_NAME,
        "skill_version": skill_version,
        "status": OutputStatus.SUCCESS.value,
        "summary": "",
        "action": action,
        "project_id": project_id,
        "task_id": task_id,
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "synthesis": None,
        "validation": {
            "input_schema": "passed",
            "output_schema": "pending",
            "self_check": "not_run",
        },
        "provenance": {
            "started_at": started_at,
            "completed_at": None,
            "skill_version": skill_version,
            "tool_versions": {"toolset": "1.0.0"},
            "input_digest": None,
        },
        "errors": [],
    }


def finalize_envelope(env: dict, completed_at: str) -> dict:
    env["provenance"]["completed_at"] = completed_at
    env["validation"]["output_schema"] = "passed"
    return env
