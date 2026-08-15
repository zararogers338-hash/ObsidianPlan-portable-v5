"""Triage: evidence layering + quality pre-screening for MICP literature.

Produces, per candidate record:
  - level: TIER1 (primary empirical, field/meter-scale) / TIER2 (lab, modelling,
    method) / TIER3 (review/tertiary navigation) / REJECT (out-of-scope or
    non-verifiable)
  - quality / comparability / bias / fulltext_available

Scoring is deterministic and transparent: every non-trivial decision carries a
`reason` string. Scale is normalized through models.SCOPE_SYNONYMS; a record
declaring no scale defaults to "unknown" and is scored conservatively.
"""

from __future__ import annotations

import re
from typing import Any

from .models import EvidenceScope, SourceKind, TriageLevel

# Journals / sources that are clearly peer-reviewed and geotechnical/geoenvironmental.
_STRONG_CONTAINER_HINTS = re.compile(
    r"geotechn|soils\s*and\s*foundations|biogeotech|civil\s*engineering|"
    r"materials|geotechnical\s*testing|water\s*resources\s*research|"
    r"computers\s*and\s*geotechn",
    flags=re.IGNORECASE,
)

# Patterns suggesting the record is a review / tertiary source.
_REVIEW_HINTS = re.compile(r"\breview\b|\boverview\b|\bsurvey\b|\bmeta[- ]analysis\b", re.IGNORECASE)

# Patterns suggesting the record is a patent or a dataset, not a paper.
_PATENT_HINTS = re.compile(r"\bpatent\b|\bWO\b|\bUS\s*\d", re.IGNORECASE)
_DATASET_HINTS = re.compile(r"\bdataset\b|\bdata\s+release\b|\brepository\b", re.IGNORECASE)

# Source-kind hints from a record's kind field or type string.
_KIND_MAP: dict[str, str] = {
    "research": SourceKind.RESEARCH.value,
    "review": SourceKind.REVIEW.value,
    "model": SourceKind.MODEL.value,
    "method": SourceKind.METHOD.value,
    "standard": SourceKind.STANDARD.value,
    "patent": SourceKind.PATENT.value,
    "dataset": SourceKind.DATASET.value,
    "book": SourceKind.BOOK.value,
    "other": SourceKind.OTHER.value,
}


def infer_kind(record: dict[str, Any]) -> str:
    """Best-effort source-kind classification from kind field, type, title, container."""
    kind = str(record.get("kind") or "").strip().lower()
    if kind in _KIND_MAP:
        return _KIND_MAP[kind]
    title = str(record.get("title") or "")
    container = str(record.get("container") or record.get("journal") or "")
    blob = f"{title} {container}"
    if _PATENT_HINTS.search(blob):
        return SourceKind.PATENT.value
    if _DATASET_HINTS.search(blob):
        return SourceKind.DATASET.value
    type_str = str(record.get("type") or "").lower()
    if "standard" in type_str:
        return SourceKind.STANDARD.value
    if _REVIEW_HINTS.search(blob):
        return SourceKind.REVIEW.value
    return SourceKind.RESEARCH.value


def normalize_scale(scope: Any) -> str:
    """Normalize a scope string into an EvidenceScope value (default unknown)."""
    text = str(scope or "").strip().lower()
    text = text.replace("_", "-").replace(" ", "-")
    return _SCOPE_SYNONYMS.get(text, "unknown")


_SCOPE_SYNONYMS = {k.replace("_", "-").replace(" ", "-"): v for k, v in {
    "lab": "lab_column", "lab_column": "lab_column", "column": "lab_column",
    "laboratory": "lab_column",
    "meter": "meter_scale", "meter_scale": "meter_scale", "meter-scale": "meter_scale",
    "pilot": "meter_scale",
    "field": "field", "field_trial": "field", "in_situ": "field", "in-situ": "field",
    "simulation": "simulation", "numerical": "simulation", "model": "simulation",
    "review": "review", "meta_analysis": "meta-analysis", "meta-analysis": "meta-analysis",
    "standard": "standard", "patent": "patent", "dataset": "dataset",
}.items()}


def _score_quality(record: dict[str, Any], kind: str) -> tuple[str, str]:
    """Return (quality, reason). Conservative when uncertain."""
    if kind == SourceKind.REVIEW.value:
        return "high", "综述/权威来源; 用于导航, 不替代原始证据"
    if kind in (SourceKind.STANDARD.value, SourceKind.PATENT.value):
        return "high", "标准或专利原文; 权威性高, 需核验原文"
    container = str(record.get("container") or record.get("journal") or "")
    if _STRONG_CONTAINER_HINTS.search(container):
        return "high", f"同行评审期刊 ({container})"
    if record.get("score"):
        try:
            if float(record["score"]) >= 0.5:
                return "medium", "来源强度中等; 需人工复核"
        except (TypeError, ValueError):
            pass
    return "low", "来源不明或非权威收录; 需人工核验"


def screen(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Screen records into tiers + rejections. Deterministic.

    Returns {"levels": [...], "rejections": [...]} matching output.schema.json `triage`.
    """
    levels: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for rec in records:
        ref_id = str(rec.get("ref_id") or "?")
        kind = infer_kind(rec)
        scale = normalize_scale(rec.get("scale"))
        doi = str(rec.get("doi") or "").strip()
        title = str(rec.get("title") or "").strip()

        # Non-verifiable / empty DOI / empty title → REJECT.
        if not doi and not title:
            rejections.append({"ref_id": ref_id, "reason": "无 DOI 且无标题, 不可核验"})
            continue
        if doi and not _valid_doi_shape(doi):
            rejections.append({"ref_id": ref_id, "reason": f"DOI 结构非法: {doi}"})
            continue

        quality, quality_reason = _score_quality(rec, kind)
        fulltext = bool(rec.get("fulltext_available"))

        # Tier decision.
        if kind == SourceKind.REVIEW.value:
            level, reason = TriageLevel.TIER3.value, "综述/三手导航证据"
        elif kind in (SourceKind.STANDARD.value, SourceKind.PATENT.value, SourceKind.DATASET.value):
            level, reason = TriageLevel.TIER2.value, f"{kind} 原文; 权威性依赖核验"
        elif scale in ("field", "meter_scale"):
            level, reason = TriageLevel.TIER1.value, f"现场/米级实证证据 ({scale})"
        elif scale == "lab_column":
            level, reason = TriageLevel.TIER2.value, "实验室柱试证据"
        elif scale == "simulation":
            level, reason = TriageLevel.TIER2.value, "数值模拟证据"
        elif kind in (SourceKind.MODEL.value, SourceKind.METHOD.value):
            level, reason = TriageLevel.TIER2.value, f"{kind} 来源"
        else:
            level, reason = TriageLevel.TIER2.value, "尺度未声明, 保守按中等证据处理"

        comparability = "high" if scale in ("field", "meter_scale", "lab_column") else "medium"
        bias = "low" if (kind in (SourceKind.RESEARCH.value,) and scale in ("field", "meter_scale")) else "medium"
        # Forged-suspicion record should not survive screening as verifiable.
        if rec.get("doi_status") == "suspected_forged":
            rejections.append({"ref_id": ref_id, "reason": "DOI 被判定为疑似伪造"})
            continue

        levels.append({
            "ref_id": ref_id,
            "level": level,
            "reason": f"{reason}; 质量={quality}({quality_reason})",
            "quality": quality,
            "comparability": comparability,
            "bias": bias,
            "fulltext_available": fulltext,
        })

    levels.sort(key=lambda item: _TIER_RANK.get(item["level"], 9))
    return {"levels": levels, "rejections": rejections}


_TIER_RANK = {TriageLevel.TIER1.value: 0, TriageLevel.TIER2.value: 1, TriageLevel.TIER3.value: 2}


def _valid_doi_shape(doi: str) -> bool:
    from .doi import is_structural_doi

    return is_structural_doi(doi)
