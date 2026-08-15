"""Typed envelope models for the micp-mineral-phase-interpreter skill.

Mirrors schemas/input.schema.json and schemas/output.schema.json. A single
definition is used by the service and by every test/example so the contract
cannot drift.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---- epistemic labels (spec §六) ---------------------------------------------
EpistemicLabel = Literal[
    "OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"
]

Status = Literal[
    "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL",
    "HUMAN_APPROVAL_REQUIRED",
]

CONTRACT_VERSION = "1.0"
SKILL_NAME = "micp-mineral-phase-interpreter"
SKILL_VERSION = "1.1.1"

# ---- input payload types -----------------------------------------------------

SampleDataType = Literal[
    "xrd_twotheta_intensity", "xrd_dspacing_intensity", "sem_image", "sem_particle_list",
    "eds_spectrum", "ftir_spectrum", "raman_spectrum", "tga_curve", "tabular",
]

EvidenceRef = TypedDict("EvidenceRef", {"ref_id": str, "uri": str | None,
                                        "media_type": str | None, "note": str | None})

UpstreamOutput = TypedDict(
    "UpstreamOutput",
    {"skill": str, "task_node": str, "output_ref": Any,
     "output": dict[str, Any] | None, "summary": str | None},
    total=False,
)


class SampleSpec(TypedDict, total=False):
    id: str
    label: str
    data_type: SampleDataType
    source: str            # provenance of the measurement
    unit_axis: str         # x-axis unit: "deg2theta", "d_A", "um", "keV", "cm-1", "degC", ...
    unit_y: str            # y-axis unit: "counts", "intensity", "wt%", ...
    unit_scale: float      # pixel-to-micron scale for sem_image (um/px); 0/absent => uncalibrated
    values: list[float] | list[list[float]] | None   # raw data
    path: str | None       # file path when provided as file instead of inline
    baseline: dict[str, Any] | None   # optional baseline/bkgd info (xrd)

    # XRD specific
    wavelength_A: float | None

    # SEM particle list: [[x_um, y_um, area_um2, ...], ...]
    particles: list[list[float]] | None
    particle_units: str | None

    # EDS / spectra: x = channel center, y = intensity
    channels: list[float] | None
    intensities: list[float] | None
    ed_kev_ca: float | None       # expected Ca K-alpha energy (default 3.690)
    ed_kev_tolerance: float | None

    # image audit
    px_width: int | None
    px_height: int | None
    scale_bar_um: float | None
    scale_bar_px: int | None


class InputEnvelope(TypedDict, total=False):
    contract_version: str
    task_id: str
    project_id: str
    request: str
    action: str
    skill_version: str
    controller_version: str
    timestamp: str

    context: dict[str, Any]
    constraints: list[str]
    evidence_refs: list[str]
    data_refs: list[str]
    upstream_outputs: list[UpstreamOutput]
    requested_output_format: str
    risk_level: str
    human_approval_state: dict[str, Any] | None
    dry_run: bool
    samples: list[SampleSpec] | None
    thresholds: dict[str, Any] | None
    save_audit_to: str | None
    max_candidate_phases: int | None
    verify_refs: bool | None
    reference_phase: str | None


# ---- output payload types ----------------------------------------------------

class LabeledStatement(TypedDict, total=False):
    statement: str
    label: EpistemicLabel
    source: str | None


class EvidenceUsed(TypedDict, total=False):
    ref_id: str
    uri: str | None
    media_type: str | None
    note: str | None


class Artifact(TypedDict, total=False):
    kind: str
    path: str | None
    note: Any


class NextSkill(TypedDict, total=False):
    skill: str
    reason: str
    inputs_needed: list[str]


class Error(TypedDict, total=False):
    code: str
    message: str
    detail: dict[str, Any]
    retryable: bool


class Validation(TypedDict, total=False):
    input_schema: str
    output_schema: str
    self_check: str
    checks: list[dict[str, Any]]


class Provenance(TypedDict, total=False):
    started_at: str | None
    completed_at: str | None
    skill_version: str | None
    sources: list[str]
    audit_log: str | None


class OutputEnvelope(TypedDict, total=False):
    contract_version: str
    skill: str
    skill_version: str
    status: Status
    summary: str
    action: str | None
    project_id: str | None
    task_id: str | None
    findings: list[LabeledStatement]
    assumptions: list[str]
    evidence_used: list[EvidenceUsed]
    uncertainty: list[str]
    risks: list[LabeledStatement]
    artifacts: list[Artifact]
    requested_next_skills: list[NextSkill]
    results: dict[str, Any]
    validation: Validation
    provenance: Provenance
    errors: list[Error]
    # flat business fields (spec §八) — optional, populated by interpret.phases
    candidate_phases: list[str]
    confirmed_phases: list[str]
    rejected_phases: list[str]
    unexplained_features: list[dict[str, Any]]
    morphology: dict[str, Any]
    spatial_distribution: dict[str, Any]
    bridge_evidence: dict[str, Any]
