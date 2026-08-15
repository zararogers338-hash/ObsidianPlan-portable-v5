"""Multi-modal evidence fusion and confidence scoring.

Turns per-modality evidence (XRD matches, SEM morphology, FTIR/Raman bands,
EDS, TGA) into a per-phase confidence score with explicit rules about what
each modality can prove. This is the module that enforces the skill's core
epistemology: an INFERRED phase identification can never be written as
OBSERVED, and a phase identification without any corroborating modality stays
a candidate/hypothesis.

Evidence weights (domain-calibrated, conservative):
  * XRD primary reflection          weight 3.0  (single strongest modality)
  * XRD secondary reflection        weight 1.0
  * FTIR/Raman matched band         weight 1.0
  * SEM morphology match            weight 0.6  (supporting only)
  * EDS Ca present                  weight 0.4  (necessary, not sufficient)
  * TGA total-loss ~stoichiometric  weight 0.6  (supports carbonate presence)

Confidence tiers (output `confidence`):
  >= 0.75  confirmed   (multi-modality, at least one primary XRD)
  >= 0.50  likely      (XRD primary + at least one corroborating modality)
  >= 0.30  candidate   (single modality or weak corroboration)
  else     weak

A phase with XRD verdict `identified` but ZERO corroborating modality is
capped at `likely` — never `confirmed` without independent evidence.

Every rule is applied deterministically and unit-tested; nothing here guesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .minerals import DIAGNOSTIC_FTIR_BANDS, DIAGNOSTIC_RAMAN_BANDS, MINERAL_PHASES, PHASE_DIAGNOSTICS

# modality contribution weights (conservative, domain-calibrated)
WEIGHTS = {
    "xrd_primary": 3.0,
    "xrd_secondary": 1.0,
    "ftir": 1.0,
    "raman": 1.0,
    "sem_morphology": 0.6,
    "eds_ca": 0.4,
    "tga_co2": 0.6,
}

# A phase reaching this weight needs corroboration from a second modality
# before it may be called confirmed.
CONFIRM_THRESHOLD = 0.75
LIKELY_THRESHOLD = 0.50
CANDIDATE_THRESHOLD = 0.30

MAX_PHASES_DEFAULT = 4


@dataclass
class PhaseFusion:
    phase: str
    score: float
    confidence: str  # confirmed | likely | candidate | weak
    evidence: dict[str, Any]  # per-modality evidence used
    weight_breakdown: dict[str, float] = field(default_factory=dict)
    xrd_verdict: str | None = None
    notes: list[str] = field(default_factory=list)


def _corroborating_modalities(evidence: dict[str, Any]) -> int:
    """Count distinct non-XRD modalities contributing *phase-diagnostic*
    positive evidence.

    FTIR only corroborates a specific phase when a polymorph-diagnostic band
    (see DIAGNOSTIC_FTIR_BANDS) was hit — a shared carbonate band (~712/713,
    ~874/877, ~1086) confirms carbonate presence but cannot differentiate
    polymorphs and therefore does NOT corroborate identity. Raman v1 is
    carbonate-generic too; only SEM morphology / EDS Ca / TGA CO2 retain
    supporting weight per their own rules.
    """
    n = 0
    if evidence.get("ftir_diagnostic"):
        n += 1
    if evidence.get("raman_diagnostic"):
        n += 1
    if evidence.get("sem_morphology"):
        n += 1
    if evidence.get("eds_ca"):
        n += 1
    if evidence.get("tga_co2"):
        n += 1
    return n


def _diagnostic_hits(bands: list[float] | None, marker_groups: list[list[float]], tol: float = 6.0) -> list[float]:
    """Bands within ``tol`` of a polymorph-diagnostic marker *group*.

    A group corroborates only when EVERY member band is present in the matched
    bands (co-occurrence). This prevents a shared v4 doublet member (~713) from
    corroborating calcite when aragonite's 854 is the real signal — the
    single-member hit no longer counts.
    """
    if not bands or not marker_groups:
        return []
    hits: list[float] = []
    for group in marker_groups:
        members = [b for b in group if any(abs(b - mb) <= tol for mb in bands)]
        if len(members) == len(group):  # full group present
            hits.extend(members)
    # dedupe, keep order
    seen: set[float] = set()
    out: list[float] = []
    for b in hits:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def fuse_phase(
    phase: str,
    xrd_verdict: str | None,
    xrd_primary_matched: bool,
    xrd_secondary_count: int,
    ftir_bands: list[float] | None = None,
    raman_bands: list[float] | None = None,
    sem_morphology: str | None = None,
    eds_ca: bool | None = None,
    tga_co2_likely: bool | None = None,
) -> PhaseFusion:
    """Compute a single phase's confidence from all available evidence.

    Explicit evidence dict per phase so the output is fully auditable: the
    caller (and the auditor) can see exactly which modality contributed what.
    FTIR/Raman corroboration is gated on polymorph-diagnostic bands.
    """
    evidence: dict[str, Any] = {}
    weight_breakdown: dict[str, float] = {}

    if xrd_verdict:
        evidence["xrd"] = {
            "verdict": xrd_verdict,
            "primary_matched": xrd_primary_matched,
            "secondary_matched": xrd_secondary_count,
        }
        if xrd_primary_matched:
            weight_breakdown["xrd_primary"] = WEIGHTS["xrd_primary"]
        weight_breakdown["xrd_secondary"] = WEIGHTS["xrd_secondary"] * min(xrd_secondary_count, 3)

    if ftir_bands:
        diag = _diagnostic_hits(ftir_bands, DIAGNOSTIC_FTIR_BANDS.get(phase, []))
        evidence["ftir"] = {"matched_bands": ftir_bands, "diagnostic_hits": diag}
        if diag:
            evidence["ftir_diagnostic"] = True
        weight_breakdown["ftir"] = WEIGHTS["ftir"]
    if raman_bands:
        diag = _diagnostic_hits(raman_bands, DIAGNOSTIC_RAMAN_BANDS.get(phase, []))
        evidence["raman"] = {"matched_bands": raman_bands, "diagnostic_hits": diag}
        if diag:
            evidence["raman_diagnostic"] = True
        weight_breakdown["raman"] = WEIGHTS["raman"]
    if sem_morphology:
        evidence["sem_morphology"] = {"matched": sem_morphology}
        weight_breakdown["sem_morphology"] = WEIGHTS["sem_morphology"]
    if eds_ca is True:
        evidence["eds_ca"] = {"present": True}
        weight_breakdown["eds_ca"] = WEIGHTS["eds_ca"]
    if tga_co2_likely is True:
        evidence["tga_co2"] = {"likely": True}
        weight_breakdown["tga_co2"] = WEIGHTS["tga_co2"]

    score = min(sum(weight_breakdown.values()) / 8.0, 1.0)  # normalize by max practical weight
    notes: list[str] = []

    corroboration = _corroborating_modalities(evidence)

    # Confidence tiers with hard epistemic caps.
    if xrd_primary_matched and score >= CONFIRM_THRESHOLD and corroboration >= 1:
        confidence = "confirmed"
    elif xrd_primary_matched and score >= LIKELY_THRESHOLD:
        confidence = "likely"
    elif score >= CANDIDATE_THRESHOLD:
        confidence = "candidate"
    else:
        confidence = "weak"

    if xrd_verdict == "identified" and corroboration == 0 and confidence == "confirmed":
        confidence = "likely"
        notes.append("XRD 单独识别,无独立模态佐证;置信度封顶为 likely(不接受仅单模态 confirmed)")

    return PhaseFusion(
        phase=phase,
        score=round(score, 4),
        confidence=confidence,
        evidence=evidence,
        weight_breakdown=weight_breakdown,
        xrd_verdict=xrd_verdict,
        notes=notes,
    )


def fuse_all(
    xrd_results: list[dict[str, Any]] | None = None,
    sem_morphology: dict[str, str] | None = None,
    spectra: dict[str, dict[str, Any]] | None = None,
    eds_ca: bool | None = None,
    tga_co2_likely: bool | None = None,
    phases: list[str] | None = None,
) -> dict[str, Any]:
    """Fuse all available evidence into per-phase confidence.

    `xrd_results`  : list of PhaseMatchResult.to_dict() (see xrd.py)
    `sem_morphology`: {phase: "rhombohedral"} — SEM-observed morphology
    `spectra`      : {phase: {"ftir": [...], "raman": [...]}} matched bands
    Returns a dict with `phases` (sorted PhaseFusion.to_dict) and `winner`.

    Explicit "no evidence for any phase" is returned as an empty list, NOT a
    fabricated winner (spec: never invent results).
    """
    phases_list = phases if phases else list(MINERAL_PHASES)
    fused: list[PhaseFusion] = []
    xrd_by_phase: dict[str, dict[str, Any]] = {}
    if xrd_results:
        for r in xrd_results:
            if isinstance(r, dict):
                xrd_by_phase[r.get("phase", "")] = r

    for phase in phases_list:
        xr = xrd_by_phase.get(phase, {})
        ftir = (spectra or {}).get(phase, {}).get("ftir")
        raman = (spectra or {}).get(phase, {}).get("raman")
        morph = (sem_morphology or {}).get(phase)
        # True secondary count: matched_peak_count includes the primary (if
        # present), which is already weighted 3.0 as xrd_primary. Counting it
        # again as secondary double-counts the reflection and lets
        # XRD+supporting-only reach 'confirmed' — a real epistemic defect.
        peak_count = int(xr.get("matched_peak_count", 0))
        primary_matched = bool(xr.get("primary_matched") if "primary_matched" in xr
                               else any(p.get("ref_confidence") == "primary"
                                        for p in xr.get("peaks", [])))
        secondary_count = max(0, peak_count - (1 if primary_matched else 0))
        fused.append(fuse_phase(
            phase,
            xrd_verdict=xr.get("verdict"),
            xrd_primary_matched=primary_matched,
            xrd_secondary_count=secondary_count,
            ftir_bands=ftir,
            raman_bands=raman,
            sem_morphology=morph,
            eds_ca=eds_ca,
            tga_co2_likely=tga_co2_likely,
        ))

    fused.sort(key=lambda f: (f.score, f.confidence), reverse=True)
    scored = [f for f in fused if f.score > 0.0]
    winner: dict[str, Any] | None = None
    if scored:
        top = scored[0]
        if top.confidence in ("confirmed", "likely"):
            winner = {
                "phase": top.phase,
                "confidence": top.confidence,
                "score": top.score,
            }
    return {
        "phases": [f.__dict__ for f in fused],
        "winner": winner,
        "winner_present": winner is not None,
    }
