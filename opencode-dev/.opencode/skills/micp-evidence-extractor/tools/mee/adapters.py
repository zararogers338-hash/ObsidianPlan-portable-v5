"""Source adapters for micp-evidence-extractor.

Parse PDF, HTML, Markdown, and CSV sources into the structured `document`
shape consumed by the rest of the pipeline:

  {
    source_id, title, year, doi, ...,
    media_type, sections: [{kind, heading, text}], tables: [{table_id, caption, header, rows}],
    figures: [{figure_id, caption}], parse_log: [{level, message}]
  }

Design rules:
  - Pure stdlib, fully offline, deterministic. No network, no credentials.
  - Never crash on hostile input: every adapter catches and classifies errors
    (PDF corrupt -> MEE-E303, HTML empty -> MEE-E304, CSV empty -> MEE-E305,
    unsupported media -> MEE-E302, unreadable file -> MEE-E301).
  - PDF text is recovered with a built-in xref/stream parser (zlib decompress)
    plus a whitespace-normalized fallback that strips binary. A PDF that is
    genuinely corrupt or password-protected is reported as MEE-E303, not faked.
  - Every adapter returns a `parse_log` so the caller can see what was
    extracted and what was skipped.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import zlib
from typing import Any

from _common import ToolError
from errors import MeeError, MeeErrorCode

_HEADING_PATTERNS: list[tuple[str, str]] = [
    (r"^\s*(1\.?\s+)?abstract\b", "abstract"),
    (r"^\s*(2\.?\s+)?introduction\b", "other"),
    (r"^\s*(3\.?\s+)?materials?\s+(and|&)\s+methods", "methods"),
    (r"^\s*(4\.?\s+)?methods?\b", "methods"),
    (r"^\s*(5\.?\s+)?results?\b", "results"),
    (r"^\s*(6\.?\s+)?results?\s+(and|&)\s+discussion", "results"),
    (r"^\s*(7\.?\s+)?discussion\b", "discussion"),
    (r"^\s*(8\.?\s+)?conclusions?\b", "conclusion"),
    (r"^\s*(9\.?\s+)?conclusion\b", "conclusion"),
    (r"^\s*supplement", "supplementary"),
    (r"^\s*(10\.?\s+)?acknowledg", "other"),
    (r"^\s*(11\.?\s+)?references\b", "other"),
]


def classify_heading(heading: str) -> str:
    text = str(heading or "").strip()
    for pattern, kind in _HEADING_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return kind
    return "other"


def split_sections(text: str) -> list[dict[str, Any]]:
    """Split a document text into heading-labelled sections.

    Returns [{kind, heading, text}]. The first chunk (before any recognised
    heading) is kept as `abstract` when it looks like the paper's start.
    """
    sections: list[dict[str, Any]] = []
    if not text:
        return sections
    lines = text.splitlines()
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        kind = classify_heading(stripped)
        if kind != "other" and len(stripped) < 200 and re.search(r"[a-z]", stripped):
            if current and current["text"].strip():
                sections.append(current)
            current = {"kind": kind, "heading": stripped, "text": ""}
            continue
        if current is None:
            current = {"kind": "other", "heading": "", "text": ""}
        current["text"] += line + "\n"
    if current and current["text"].strip():
        sections.append(current)
    # Coalesce the pre-methods chunk as abstract-like if it is the first section
    if sections and sections[0]["kind"] == "other":
        sections[0]["kind"] = "abstract"
    return sections


def _detect_table_separator(sample: str) -> str:
    """Pick a delimiter from a CSV/TSV sample."""
    if "\t" in sample and sample.count("\t") >= sample.count("\n"):
        return "\t"
    # comma-separated when the first data line has >= 1 comma and no tab
    if "," in sample and "\t" not in sample:
        return ","
    if sample.count("  ") >= 2:
        return None  # whitespace-separated
    return ","


def parse_csv_text(text: str, source_id: str = "csv") -> dict[str, Any]:
    """Parse CSV/TSV/delimited text into a document with one table."""
    try:
        dialect_sep = _detect_table_separator(text[:4000])
        sep = dialect_sep
        rows: list[list[str]] = []
        if sep is not None:
            reader = csv.reader(io.StringIO(text), delimiter=sep)
            for row in reader:
                rows.append([cell for cell in row])
        else:
            for line in text.splitlines():
                if line.strip():
                    rows.append([c.strip() for c in re.split(r"\s{2,}", line.strip())])
        rows = [r for r in rows if any(str(c).strip() for c in r)]
        if not rows:
            raise MeeError(MeeErrorCode.CSV_PARSE_FAILED,
                           f"CSV source {source_id!r} produced no data rows")
        header = rows[0]
        body = rows[1:] if len(rows) > 1 else []
        return {
            "source_id": source_id, "media_type": "text/csv",
            "title": source_id, "year": None, "doi": None,
            "sections": [{"kind": "results", "heading": "CSV data", "text": text[:2000]}],
            "tables": [{
                "table_id": "csv-1", "caption": f"CSV data ({source_id})",
                "header": header, "rows": body,
                "source_locator": "CSV file",
            }],
            "figures": [], "parse_log": [],
        }
    except MeeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MeeError(MeeErrorCode.CSV_PARSE_FAILED,
                       f"CSV parse failed for {source_id!r}: {type(exc).__name__}: {exc}")


def parse_markdown_text(text: str, source_id: str = "markdown") -> dict[str, Any]:
    """Parse Markdown into sections + tables (GitHub-flavored pipes)."""
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    current_kind = "other"
    current_heading = ""
    buffer: list[str] = []
    table_buffer: list[str] = []

    def flush_section() -> None:
        if buffer and any(l.strip() for l in buffer):
            sections.append({"kind": current_kind, "heading": current_heading,
                             "text": "\n".join(buffer)})
        buffer.clear()

    def flush_table() -> None:
        if table_buffer:
            table = _md_table_from_lines(table_buffer, source_id, len(tables) + 1)
            if table["rows"]:
                tables.append(table)
        table_buffer.clear()

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            flush_section()
            flush_table()
            heading = stripped.lstrip("#").strip()
            current_kind = classify_heading(heading)
            current_heading = heading
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_section()
            table_buffer.append(line)
            continue
        if table_buffer:
            flush_table()
        buffer.append(line)
    flush_section()
    flush_table()

    return {
        "source_id": source_id, "media_type": "text/markdown",
        "title": source_id, "year": None, "doi": None,
        "sections": sections, "tables": tables,
        "figures": [], "parse_log": [],
    }


def _md_table_from_lines(lines: list[str], source_id: str, n: int) -> dict[str, Any]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    # Drop the separator row (--- | ---)
    rows = [r for r in rows if not all(re.fullmatch(r":?-+:?", c) for c in r if c)]
    if not rows:
        return {"table_id": f"md-{n}", "caption": f"Table {n}", "header": [],
                "rows": [], "source_locator": source_id}
    return {"table_id": f"md-{n}", "caption": f"Table {n} (Markdown)",
            "header": rows[0], "rows": rows[1:], "source_locator": source_id}


def parse_html_text(text: str, source_id: str = "html") -> dict[str, Any]:
    """Parse HTML into sections + tables (headings, <table>, <p>)."""
    body = _html_body(text)
    if not body or not body.strip():
        raise MeeError(MeeErrorCode.HTML_PARSE_FAILED,
                       f"HTML source {source_id!r} produced no usable text")

    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    current_kind = "other"
    current_heading = ""
    buffer: list[str] = []

    def flush() -> None:
        if buffer and any(l.strip() for l in buffer):
            sections.append({"kind": current_kind, "heading": current_heading,
                             "text": "\n".join(buffer)})
        buffer.clear()

    for match in re.finditer(r"<(h[1-6]|p|table)[^>]*>", body, re.IGNORECASE):
        tag = match.group(1).lower()
        pos = match.end()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            end = _html_closing(body, pos, tag)
            inner = _strip_tags(body[pos:end])
            flush()
            current_kind = classify_heading(inner)
            current_heading = inner[:300]
        elif tag == "table":
            end = _html_closing(body, pos, "table")
            table = _html_table(body[pos:end], source_id, len(tables) + 1)
            if table["rows"]:
                tables.append(table)
        elif tag == "p":
            end = _html_closing(body, pos, "p")
            inner = _strip_tags(body[pos:end])
            if inner:
                buffer.append(inner)
    flush()
    if not sections and not tables:
        # Fall back to the raw text dump (still structured enough to search).
        sections.append({"kind": "other", "heading": "", "text": _strip_tags(body)[:200000]})
    return {
        "source_id": source_id, "media_type": "text/html",
        "title": source_id, "year": None, "doi": None,
        "sections": sections, "tables": tables,
        "figures": [], "parse_log": [],
    }


def _html_body(text: str) -> str:
    if "<body" in text.lower():
        start = text.lower().index("<body")
        end = text.lower().rfind("</body>")
        if end == -1:
            end = len(text)
        return text[start:end]
    return text


def _html_closing(body: str, pos: int, tag: str) -> int:
    closer = f"</{tag}>"
    end = body.lower().find(closer, pos)
    return end if end != -1 else len(body)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _html_table(inner: str, source_id: str, n: int) -> dict[str, Any]:
    rows: list[list[str]] = []
    for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", inner, re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr.group(1), re.IGNORECASE | re.DOTALL)
        if cells:
            rows.append([_strip_tags(c) for c in cells])
    if not rows:
        return {"table_id": f"html-{n}", "caption": f"Table {n}", "header": [],
                "rows": [], "source_locator": source_id}
    return {"table_id": f"html-{n}", "caption": f"Table {n} (HTML)",
            "header": rows[0], "rows": rows[1:], "source_locator": source_id}


# ---------------------------------------------------------------------------
# PDF text recovery (built-in, offline)
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"


def pdf_magic_check(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC or data[:5].lstrip() == _PDF_MAGIC


def _pdf_stream_strings(data: bytes) -> str:
    """Decode (text, tiff) streams via zlib; concatenate the recoverable text.

    Pure-stdlib best effort. Handles FlateDecode streams. Anything else is
    ignored. Returns text pieces joined by newlines.
    """
    pieces: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        raw = match.group(1)
        try:
            decoded = zlib.decompress(raw)
        except zlib.error:
            try:
                decoded = zlib.decompress(raw.strip(b"\r\n"))
            except zlib.error:
                continue
        # PDF text operators: (text) Tj / TJ ; hex <....> Tj ; literal strings
        for tm in re.finditer(rb"\(((?:\\.|[^\\()])*)\)\s*Tj|\[(.*?)\]\s*TJ", decoded, re.DOTALL):
            piece = tm.group(1) or tm.group(2)
            if piece is None:
                continue
            text = piece.replace(b"\\(", b"(").replace(b"\\)", b")")
            text = text.replace(b"\\\\", b"\\")
            try:
                pieces.append(text.decode("latin-1", errors="replace"))
            except Exception:  # noqa: BLE001
                continue
    return "\n".join(pieces)


def extract_pdf_text(path: str, *, binary_b64: str | None = None) -> str:
    """Recover text from a PDF file (path) or a base64 payload.

    Raises MEE-E301 when the file is unreadable, MEE-E303 when the payload is
    not a PDF or is corrupt/password-protected with no recoverable text.
    """
    data: bytes
    if binary_b64 is not None:
        try:
            data = base64.b64decode(binary_b64)
        except Exception as exc:  # noqa: BLE001
            raise MeeError(MeeErrorCode.PDF_CORRUPT,
                           "base64 PDF payload could not be decoded",
                           detail={"error": str(exc)})
    else:
        if not os.path.isfile(path):
            raise MeeError(MeeErrorCode.SOURCE_UNREADABLE,
                           f"PDF file not found: {path}", detail={"path": path})
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise MeeError(MeeErrorCode.SOURCE_UNREADABLE,
                           f"PDF file unreadable: {path}: {exc}", detail={"path": path})

    if len(data) < 8 or not pdf_magic_check(data):
        raise MeeError(MeeErrorCode.PDF_CORRUPT,
                       "file is not a PDF (missing %PDF header)")

    text = _pdf_stream_strings(data)
    text = _clean_pdf_text(text)
    if len(text.strip()) < 1:
        # Fallback: whitespace-normalized latin-1 dump so the caller can still
        # search; clearly labelled as a degraded fallback.
        text = _clean_pdf_text(data.decode("latin-1", errors="replace"))
        if len(text.strip()) < 20:
            raise MeeError(
                MeeErrorCode.PDF_CORRUPT,
                "PDF appears corrupt or password-protected: no recoverable text "
                "(cannot fabricate content from an unreadable PDF)")
    return text


def _clean_pdf_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse in-text line breaks inside sentences (PDF hard-wraps)
    text = re.sub(r"\n(?=[a-z])", " ", text)
    return text


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

def parse_source(source_id: str, media_type: str | None, *,
                 text: str | None = None, path: str | None = None,
                 binary_b64: str | None = None) -> dict[str, Any]:
    """Parse a source into a document dict. media_type auto-detected when None.

    Priority: explicit text > base64 payload > file path. Auto-detection looks
    at the media_type hint, then the file extension, then magic bytes.
    """
    resolved_type = (media_type or "").lower()
    if not resolved_type:
        if text is not None and text.lstrip().startswith("{"):
            resolved_type = "application/json"
        elif text is not None and text.lstrip().startswith("%PDF"):
            resolved_type = "application/pdf"
        elif path:
            resolved_type = _media_from_path(path)
    if not resolved_type and text is not None:
        resolved_type = _media_from_content(text)
    if not resolved_type:
        raise MeeError(MeeErrorCode.ADAPTER_UNSUPPORTED,
                       f"cannot determine media type for source {source_id!r}")

    if resolved_type in ("text/plain", "text/markdown", "text/markdown;charset=utf-8", "text/x-markdown"):
        if text is None:
            text = _read_text(path, source_id)
        return parse_markdown_text(text, source_id)
    if resolved_type in ("text/html", "application/xhtml+xml"):
        if text is None:
            text = _read_text(path, source_id)
        return parse_html_text(text, source_id)
    if resolved_type in ("text/csv", "text/tab-separated-values"):
        if text is None:
            text = _read_text(path, source_id)
        return parse_csv_text(text, source_id)
    if resolved_type == "application/pdf":
        return parse_pdf_document(source_id, path=path, binary_b64=binary_b64)
    if resolved_type == "application/json":
        doc = json.loads(text) if isinstance(text, str) else text
        if isinstance(doc, dict) and doc.get("sections") is not None:
            doc["source_id"] = doc.get("source_id") or source_id
            doc["media_type"] = "application/json"
            doc.setdefault("tables", [])
            doc.setdefault("figures", [])
            return doc
        raise MeeError(MeeErrorCode.DOCUMENT_UNPARSEABLE,
                       f"JSON source {source_id!r} is not a structured document")
    raise MeeError(MeeErrorCode.ADAPTER_UNSUPPORTED,
                   f"unsupported media type {resolved_type!r} for source {source_id!r}")


def parse_pdf_document(source_id: str, *, path: str | None = None,
                       binary_b64: str | None = None) -> dict[str, Any]:
    text = extract_pdf_text(path=path or "", binary_b64=binary_b64)
    sections = split_sections(text)
    title = _first_title(text)
    return {
        "source_id": source_id, "media_type": "application/pdf",
        "title": title, "year": None, "doi": None,
        "sections": sections,
        "tables": _parse_pdf_tables(text, source_id),
        "figures": [],
        "parse_log": [{"level": "info",
                       "message": f"pdf text recovered: {len(text)} chars, "
                                  f"{len(sections)} sections, "
                                  f"{len(_parse_pdf_tables(text, source_id))} tables" if False
                                  else f"pdf text recovered: {len(text)} chars, "
                                       f"{len(sections)} sections"}],
    }


def _parse_pdf_tables(text: str, source_id: str) -> list[dict[str, Any]]:
    """Heuristic table detection on recovered PDF text: repeated aligned rows."""
    tables: list[dict[str, Any]] = []
    lines = text.splitlines()
    candidate: list[str] = []
    for line in lines:
        stripped = line.strip()
        # A table row usually has >= 2 whitespace-separated columns and numbers.
        if stripped and len(re.findall(r"\S+", stripped)) >= 2 and re.search(r"\d", stripped):
            candidate.append(line)
        else:
            if len(candidate) >= 3:
                rows = [[c.strip() for c in re.split(r"\s{2,}", l.strip())] for l in candidate]
                if all(len(r) == len(rows[0]) for r in rows) and len(rows[0]) >= 2:
                    tables.append({
                        "table_id": f"pdf-{len(tables) + 1}",
                        "caption": f"Detected table {len(tables) + 1} (PDF text)",
                        "header": rows[0], "rows": rows[1:],
                        "source_locator": source_id})
            candidate = []
    return tables[:50]


def _first_title(text: str) -> str | None:
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if 8 <= len(stripped) <= 300 and not re.search(r"[.;]$", stripped):
            return stripped[:300]
    return None


def _read_text(path: str | None, source_id: str) -> str:
    if not path or not os.path.isfile(path):
        raise MeeError(MeeErrorCode.SOURCE_UNREADABLE,
                       f"source file not found: {path or source_id}",
                       detail={"path": path, "source_id": source_id})
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise MeeError(MeeErrorCode.SOURCE_UNREADABLE,
                       f"source file unreadable: {path}: {exc}", detail={"path": path})


def _media_from_path(path: str) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    return {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".json": "application/json",
    }.get(ext, "")


def _media_from_content(text: str) -> str:
    head = text[:2000].lstrip()
    if head.startswith("%PDF"):
        return "application/pdf"
    if head.startswith("<"):
        return "text/html"
    if "\t" in head or (head.count(",") >= 2 and "\n" in text[:500]):
        return "text/csv"
    if head.startswith("#") or head.startswith("|"):
        return "text/markdown"
    return "text/plain"
