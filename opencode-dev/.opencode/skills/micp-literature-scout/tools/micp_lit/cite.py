"""Citation export: BibTeX / CSL-JSON / CSV / RIS generators.

Zero third-party dependencies (project requirement: reuse mature libs when
present — bibtexparser is not installed in this environment, so we implement
a small, standards-shaped generator and validate it with tests instead).
Field escaping is strict so round-tripping parsers stay happy.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from .dedup import normalize_title

BIBTEX_ENTRY_TYPES = {
    "article", "book", "inbook", "incollection", "inproceedings",
    "phdthesis", "misc", "proceedings", "techreport",
}

# Regex: Unicode letters/digits plus a safe subset for citation keys.
_CITEKEY_SAFE = re.compile(r"[^A-Za-z0-9_:\-.]")


def _citekey(rec: dict[str, Any], idx: int) -> str:
    """Deterministic citation key: first-author surname + year + short title."""
    authors = rec.get("authors") or rec.get("author") or []
    surname = ""
    if authors:
        first = str(authors[0])
        parts = first.split()
        surname = _CITEKEY_SAFE.sub("", parts[-1] if parts else "").lower()
    year = str(rec.get("year") or "")
    title = normalize_title(str(rec.get("title") or ""))
    # Take first 4 significant words.
    words = [w for w in title.split() if w not in {"the", "and", "for", "of", "a"}][:4]
    short = "-".join(words).lower()
    base = f"{surname or 'anon'}{year}{short}" or f"ref{idx}"
    return base[:60] or f"ref{idx}"


def _bibtex_type(kind: str) -> str:
    if kind == "standard":
        return "techreport"
    if kind == "patent":
        return "misc"
    if kind == "dataset":
        return "misc"
    return "article"


def _bibtex_escape(text: Any) -> str:
    """Escape braces, %, & and unicode for BibTeX content fields."""
    s = str(text or "")
    s = s.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    s = s.replace("%", r"\%").replace("&", r"\&")
    return s


def _authors_bibtex(rec: dict[str, Any]) -> str:
    authors = rec.get("authors") or rec.get("author") or []
    return " and ".join(_bibtex_escape(a) for a in authors)


def to_bibtex(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, rec in enumerate(records):
        key = rec.get("ref_id") and _CITEKEY_SAFE.sub("", str(rec["ref_id"])) or _citekey(rec, idx)
        kind = str(rec.get("kind") or "research")
        etype = _bibtex_type(kind)
        lines.append(f"@{etype}{{{key},")
        lines.append(f"  title = {{{_bibtex_escape(rec.get('title'))}}},")
        authors = _authors_bibtex(rec)
        if authors:
            lines.append(f"  author = {{{authors}}},")
        if rec.get("year") is not None:
            lines.append(f"  year = {{{rec['year']}}},")
        container = rec.get("container") or rec.get("journal")
        if container:
            field = "journal" if etype == "article" else "booktitle"
            lines.append(f"  {field} = {{{_bibtex_escape(container)}}},")
        if rec.get("doi"):
            lines.append(f"  doi = {{{rec['doi']}}},")
        if rec.get("volume"):
            lines.append(f"  volume = {{{rec['volume']}}},")
        if rec.get("pages"):
            lines.append(f"  pages = {{{rec['pages']}}},")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def to_csl_json(records: list[dict[str, Any]]) -> str:
    """CSL-JSON (citeproc-js) bibliography items."""
    items: list[dict[str, Any]] = []
    for rec in records:
        authors = rec.get("authors") or rec.get("author") or []
        item: dict[str, Any] = {
            "id": str(rec.get("ref_id") or _citekey(rec, 0)),
            "type": _csl_type(rec),
            "title": str(rec.get("title") or ""),
        }
        if authors:
            item["author"] = [{"family": a.split()[-1] if a.split() else "",
                               "given": " ".join(a.split()[:-1])} for a in authors]
        if rec.get("year") is not None:
            item["issued"] = {"date-parts": [[int(rec["year"])]]}
        container = rec.get("container") or rec.get("journal")
        if container:
            item["container-title"] = str(container)
        if rec.get("doi"):
            item["DOI"] = str(rec["doi"])
        if rec.get("volume"):
            item["volume"] = str(rec["volume"])
        if rec.get("pages"):
            item["page"] = str(rec["pages"])
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=2)


def _csl_type(rec: dict[str, Any]) -> str:
    kind = str(rec.get("kind") or "research")
    if kind == "standard":
        return "report"
    if kind == "patent":
        return "patent"
    if kind == "dataset":
        return "dataset"
    return "article-journal"


def to_csv(records: list[dict[str, Any]]) -> str:
    """CSV with a stable column set; deterministic order."""
    columns = ["ref_id", "doi", "title", "year", "container", "authors", "kind", "scale", "doi_status"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        row = {c: rec.get(c) for c in columns}
        authors = rec.get("authors") or rec.get("author") or []
        row["authors"] = "; ".join(str(a) for a in authors)
        writer.writerow(row)
    return buf.getvalue()


def to_ris(records: list[dict[str, Any]]) -> str:
    """RIS export (R1/R2 tag style)."""
    lines: list[str] = []
    type_map = {"article": "JOUR", "review": "JOUR", "model": "JOUR",
                "method": "JOUR", "standard": "RPRT", "patent": "PAT",
                "dataset": "DATA", "book": "BOOK", "other": "MISC"}
    for rec in records:
        lines.append("TY  - " + type_map.get(str(rec.get("kind") or "article"), "JOUR"))
        lines.append(f"TI  - {rec.get('title') or ''}")
        authors = rec.get("authors") or rec.get("author") or []
        for a in authors:
            lines.append(f"AU  - {a}")
        if rec.get("year") is not None:
            lines.append(f"PY  - {rec['year']}")
        container = rec.get("container") or rec.get("journal")
        if container:
            lines.append(f"JO  - {container}")
        if rec.get("doi"):
            lines.append(f"DO  - {rec['doi']}")
        lines.append("ER  -")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


FORMATS: dict[str, Any] = {
    "bibtex": to_bibtex,
    "json": to_csl_json,
    "csv": to_csv,
    "ris": to_ris,
}


def export(records: list[dict[str, Any]], fmt: str = "bibtex") -> str:
    """Export records in the requested format. Raises ValueError on unknown fmt."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt}; expected one of {sorted(FORMATS)}")
    return FORMATS[fmt](records)
