"""Dedup: merge candidate records under three deterministic rules.

Rules (in priority order, first match wins):
  1. doi       — same normalized DOI
  2. title_norm— identical normalized title (lowercase, punctuation/case folded)
  3. title_year_journal — same normalized title + year + journal

Deterministic: no randomness, no wall-clock. Input order is preserved for
canonical selection (first seen wins).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_TITLE_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")

# Crossref/OpenAlex return DOIs in various casings; normalize to lowercase
# without the "https://doi.org/" prefix so identical DOIs always merge.
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


def normalize_title(title: str) -> str:
    """Fold title for comparison: NFD, drop marks, lowercase, strip punctuation/whitespace."""
    text = unicodedata.normalize("NFD", str(title or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = _TITLE_PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip().lower()


def normalize_doi(doi: Any) -> str:
    """Return a lowercase DOI without scheme prefix, or "" if absent/invalid."""
    if doi is None:
        return ""
    text = str(doi).strip()
    for prefix in DOI_PREFIXES:
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    return text.strip().lower()


def _get(rec: dict[str, Any], key: str) -> Any:
    return rec.get(key)


def _as_str(rec: dict[str, Any], key: str) -> str:
    val = _get(rec, key)
    return str(val) if val is not None else ""


def merge_group(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge records into canonical+merged groups.

    Returns a list of groups:
      {"canonical": ref_id, "merged": [ref_id, ...], "rule": "doi|title_norm|title_year_journal"}
    Each input record must carry a "ref_id". Records with duplicate ref_ids are
    themselves collapsed (first wins).
    """
    groups: list[dict[str, Any]] = []
    index: list[tuple[str, str, str, str, int]] = []  # (doi, title, year, journal, group_idx)
    seen_refs: set[str] = set()

    def _find_group(rec: dict[str, Any]) -> tuple[str, int] | None:
        doi = normalize_doi(_get(rec, "doi"))
        title = normalize_title(_as_str(rec, "title"))
        year = _as_str(rec, "year")
        journal = normalize_title(_as_str(rec, "container") or _as_str(rec, "journal"))
        for i, (g_doi, g_title, g_year, g_journal, _idx) in enumerate(index):
            if doi and g_doi and doi == g_doi:
                return "doi", i
            # Title-only matching is only safe when neither record carries
            # disambiguating year/journal (e.g. book chapters with empty years).
            if (
                title and g_title and title == g_title
                and not year and not g_year and not journal and not g_journal
            ):
                return "title_norm", i
            if (
                title and g_title and title == g_title
                and year and g_year and year == g_year
                and journal and g_journal and journal == g_journal
            ):
                return "title_year_journal", i
        return None

    for rec in records:
        ref_id = _as_str(rec, "ref_id") or f"rec{len(groups) + 1}"
        if ref_id in seen_refs:
            continue  # identical ref already processed
        seen_refs.add(ref_id)
        hit = _find_group(rec)
        if hit is None:
            groups.append({"canonical": ref_id, "merged": [], "rule": None})
            index.append((
                normalize_doi(_get(rec, "doi")),
                normalize_title(_as_str(rec, "title")),
                _as_str(rec, "year"),
                normalize_title(_as_str(rec, "container") or _as_str(rec, "journal")),
                len(groups) - 1,
            ))
        else:
            rule, idx = hit
            groups[idx]["merged"].append(ref_id)
            # canonical is the first seen ref_id in this group
            if groups[idx]["rule"] is None:
                groups[idx]["rule"] = rule

    # Fill rule for singletons as "none" (schema expects a value).
    for g in groups:
        if g["rule"] is None:
            g["rule"] = "none"
    return groups


def dedup_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Public entry: dedup a list of records → dedup report + unique records.

    Returns {"input_count", "output_count", "merged_groups", "unique_records"}.
    `unique_records` keeps the first record of each group so downstream
    (triage/cite) operates on canonical entries only.
    """
    groups = merge_group(records)
    # canonical ref_id → the record that owns it (first-seen in its group).
    canonical_records: dict[str, dict[str, Any]] = {}
    canonical_order: list[str] = []
    for rec in records:
        ref_id = _as_str(rec, "ref_id") or f"rec{len(canonical_order) + 1}"
        if ref_id not in canonical_records:
            canonical_records[ref_id] = rec
            canonical_order.append(ref_id)
    unique = [canonical_records[g["canonical"]] for g in groups if g["canonical"] in canonical_records]
    group_report = [
        {"canonical": g["canonical"], "merged": list(g["merged"]), "rule": g["rule"]}
        for g in groups
    ]
    return {
        "input_count": len(records),
        "output_count": len(unique),
        "merged_groups": group_report,
        "unique_records": unique,
    }
