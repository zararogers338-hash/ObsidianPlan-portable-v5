"""Search adapters: OpenAlex / Crossref / PubMed, plus query building and
offline-fixture fallback.

Engineering requirements (spec §五):
- timeouts (default 15s), retries (2), error classification (network / HTTP /
  timeout / parse), logging, offline degradation.
- No keys in the repo; no secrets in this file.
- Never default to network-available: tests and CI run --offline against
  tools/fixtures/.
- A dry-run path never touches the network.

Determinism note: live results vary with upstream relevance ranking. The
`repro_id` fingerprints the *query* (normalized), not upstream bytes; offline
fixture mode is fully deterministic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from .errors import e403_timeout, e404_database_error, MlsError

log = logging.getLogger("micp_lit.adapters")

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2
USER_AGENT = "micp-literature-scout/1.0.0 (mailto:research@example.com)"

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Time-range filter support: "2015-2026" or "2020-"
_RANGE_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})?\s*$")


def parse_time_range(value: Any) -> tuple[int | None, int | None]:
    """Parse a time range spec into (start, end) or (None, None)."""
    if value is None:
        return None, None
    m = _RANGE_RE.match(str(value))
    if not m:
        return None, None
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else None
    return start, end


class SearchError(MlsError):
    """Raised when a database cannot serve a request after all retries."""


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Classify an exception into (category, short description)."""
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, TimeoutError):
        return "timeout", text
    if name == "ConnectionError" or name == "ConnectTimeoutError" or "timed out" in text.lower():
        return "network", text
    if name == "HTTPError" and "429" in text:
        return "rate_limit", text
    if name in ("JSONDecodeError", "ValueError"):
        return "parse", text
    return "unknown", text


def _request_once(url: str, params: dict[str, Any], timeout: float, transport: Callable[..., Any] | None) -> Any:
    """One HTTP GET. Injected transport returns the parsed JSON for tests."""
    if transport is not None:
        return transport(url, params, timeout)
    import requests

    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def http_get_json(
    url: str,
    params: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    transport: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET with retry + backoff. Raises SearchError with classified cause."""
    last: BaseException | None = None
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            data = _request_once(url, params, timeout, transport)
            if data is not None:
                return data
            return None
        except BaseException as exc:  # noqa: BLE001
            last = exc
            category, _ = classify_exception(exc)
            elapsed = time.monotonic() - t0
            log.warning("adapter error url=%s attempt=%d/%d category=%s elapsed=%.2fs err=%s",
                        url, attempt + 1, retries + 1, category, elapsed, exc)
            if attempt < retries:
                sleep(min(1.0 * (2 ** attempt), 4.0))
    assert last is not None
    category, desc = classify_exception(last)
    if category == "timeout":
        raise SearchError(**e403_timeout(url, timeout).__dict__) from last
    raise SearchError(**e404_database_error(url, -1, f"{category}: {desc}").__dict__) from last


class BaseAdapter:
    """Common shape for all adapters."""

    name = "base"

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.transport = transport
        self.sleep = sleep

    def search(self, query: str, n: int = 10, time_range: tuple[int | None, int | None] = (None, None)) -> list[dict[str, Any]]:
        raise NotImplementedError


def _make_ref_id(seed: str, index: int) -> str:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"rec-{h}-{index}"


class OpenAlexAdapter(BaseAdapter):
    """OpenAlex /works search."""

    name = "openalex"

    def search(self, query: str, n: int = 10, time_range: tuple[int | None, int | None] = (None, None)) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "search": query,
            "per-page": n,
            "sort": "relevance_score:desc",
            "mailto": "research@example.com",
        }
        if time_range[0]:
            params["filter"] = f"from_publication_date:{time_range[0]}-01-01"
        url = "https://api.openalex.org/works"
        data = http_get_json(url, params, timeout=self.timeout, retries=self.retries,
                             transport=self.transport, sleep=self.sleep)
        if data is None:
            return []
        out: list[dict[str, Any]] = []
        for idx, w in enumerate(data.get("results", []) or []):
            src = (w.get("primary_location") or {}).get("source") or {}
            doi = w.get("doi") or ""
            out.append({
                "ref_id": _make_ref_id(f"openalex:{query}:{doi or idx}", idx),
                "doi": (doi.split("doi.org/")[-1] if doi else ""),
                "title": w.get("display_name") or "",
                "year": w.get("publication_year"),
                "container": src.get("display_name") or "",
                "source_db": "openalex",
                "score": w.get("relevance_score"),
                "doi_status": "not_checked",
                "kind": "research",
                "scale": "unknown",
            })
        return out


class CrossrefAdapter(BaseAdapter):
    """Crossref /works bibliographic search."""

    name = "crossref"

    def search(self, query: str, n: int = 10, time_range: tuple[int | None, int | None] = (None, None)) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query.bibliographic": query,
            "rows": n,
            "select": "DOI,title,container-title,type,published,author,is-referenced-by-count,score",
        }
        if time_range[0] and time_range[1]:
            params["filter"] = f"from-pub-date:{time_range[0]}-01-01,until-pub-date:{time_range[1]}-12-31"
        elif time_range[0]:
            params["filter"] = f"from-pub-date:{time_range[0]}-01-01"
        url = "https://api.crossref.org/works"
        data = http_get_json(url, params, timeout=self.timeout, retries=self.retries,
                             transport=self.transport, sleep=self.sleep)
        if data is None:
            return []
        out: list[dict[str, Any]] = []
        for idx, it in enumerate((data.get("message", {}) or {}).get("items", []) or []):
            title = (it.get("title") or [""])[0]
            container = (it.get("container-title") or [""])[0]
            year = None
            date_parts = (it.get("published") or {}).get("date-parts") or [[None]]
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
            out.append({
                "ref_id": _make_ref_id(f"crossref:{query}:{it.get('DOI', '')}", idx),
                "doi": it.get("DOI") or "",
                "title": title,
                "year": year,
                "container": container,
                "source_db": "crossref",
                "score": it.get("score"),
                "doi_status": "not_checked",
                "kind": "research",
                "scale": "unknown",
                "authors": [f"{a.get('family', '')} {a.get('given', '')}".strip() for a in (it.get("author") or [])],
            })
        return out


class PubMedAdapter(BaseAdapter):
    """PubMed E-utilities esearch + efetch summary. Implemented as available;
    in this environment we use esummary. If ESearch fails, raises SearchError
    which the service degrades from."""

    name = "pubmed"

    def search(self, query: str, n: int = 10, time_range: tuple[int | None, int | None] = (None, None)) -> list[dict[str, Any]]:
        ids = self._esearch(query, n, time_range)
        if not ids:
            return []
        return self._esummary(ids)

    def _esearch(self, query: str, n: int, time_range: tuple[int | None, int | None]) -> list[str]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": n,
            "retmode": "json",
            "tool": "micp-literature-scout",
            "email": "research@example.com",
        }
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        data = http_get_json(url, params, timeout=self.timeout, retries=self.retries,
                             transport=self.transport, sleep=self.sleep)
        if data is None:
            return []
        idlist = (((data.get("esearchresult") or {}).get("idlist")) or [])
        return [str(i) for i in idlist]

    def _esummary(self, ids: list[str]) -> list[dict[str, Any]]:
        params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": "micp-literature-scout",
            "email": "research@example.com",
        }
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        data = http_get_json(url, params, timeout=self.timeout, retries=self.retries,
                             transport=self.transport, sleep=self.sleep)
        if data is None:
            return []
        out: list[dict[str, Any]] = []
        result = (data.get("result") or {})
        for idx, pmid in enumerate(ids):
            r = result.get(pmid) or {}
            authors = [f"{a.get('name', '')}" for a in (r.get("authors") or [])]
            out.append({
                "ref_id": _make_ref_id(f"pubmed:{pmid}", idx),
                "doi": (r.get("elocationid") or "").replace("doi: ", ""),
                "title": r.get("title") or "",
                "year": int(r.get("pubdate", "0")[:4]) if r.get("pubdate") else None,
                "container": (r.get("fulljournalname") or r.get("source") or ""),
                "source_db": "pubmed",
                "score": None,
                "doi_status": "not_checked",
                "kind": "research",
                "scale": "unknown",
                "authors": authors,
            })
        return out


class OfflineFixtureAdapter(BaseAdapter):
    """Reads a canned results set from tools/fixtures/ and applies filters.
    Fully deterministic — used for --offline, tests, and automatic fallback."""

    name = "offline_fixture"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        super().__init__()
        self.fixture_dir = Path(fixture_dir or FIXTURE_DIR)

    def load(self, name: str) -> list[dict[str, Any]]:
        path = self.fixture_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"fixture missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def search(self, query: str, n: int = 10, time_range: tuple[int | None, int | None] = (None, None)) -> list[dict[str, Any]]:
        records = self.load("micp_search_results.json")
        text = query.lower()
        hit = [
            r for r in records
            if any(w in str(r.get("title", "")).lower() or w in str(r.get("abstract", "")).lower()
                   for w in text.split() if len(w) >= 3)
        ] or records
        start, end = time_range
        if start or end:
            hit = [
                r for r in hit
                if (start is None or int(r.get("year") or 0) >= start)
                and (end is None or int(r.get("year") or 0) <= end)
            ]
        for i, r in enumerate(hit[:n]):
            r["source_db"] = "offline_fixture"
            r["doi_status"] = r.get("doi_status", "not_checked")
        return hit[:n]


ADAPTERS: dict[str, type[BaseAdapter]] = {
    "openalex": OpenAlexAdapter,
    "crossref": CrossrefAdapter,
    "pubmed": PubMedAdapter,
}


def build_adapters(
    *,
    database: str,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    transport: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[BaseAdapter]:
    """Instantiate adapters for a database choice. 'auto' → all live adapters
    plus offline fallback (offline always last)."""
    if database == "offline_fixture":
        return [OfflineFixtureAdapter()]
    if database == "auto":
        adapters = [OpenAlexAdapter(timeout=timeout, retries=retries, transport=transport, sleep=sleep),
                    CrossrefAdapter(timeout=timeout, retries=retries, transport=transport, sleep=sleep),
                    PubMedAdapter(timeout=timeout, retries=retries, transport=transport, sleep=sleep)]
        adapters.append(OfflineFixtureAdapter())
        return adapters
    if database in ADAPTERS:
        return [ADAPTERS[database](timeout=timeout, retries=retries, transport=transport, sleep=sleep),
                OfflineFixtureAdapter()]
    raise ValueError(f"unknown database: {database}")


def search_all(
    query: str,
    *,
    database: str = "auto",
    n: int = 10,
    time_range: tuple[int | None, int | None] = (None, None),
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    transport: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Try adapters in order; first successful live result wins; offline fixture
    is the final fallback. Returns (records, used_db, warnings)."""
    adapters = build_adapters(database=database, timeout=timeout, retries=retries,
                              transport=transport, sleep=sleep)
    warnings: list[str] = []
    for adapter in adapters:
        if adapter.name == "offline_fixture":
            try:
                records = adapter.search(query, n=n, time_range=time_range)
                warnings.append("网络适配器不可用; 已降级到离线 fixture")
                return records, "offline_fixture", warnings
            except FileNotFoundError as exc:
                raise SearchError("MLS-E402", "网络不可用且离线 fixture 缺失", {"missing": str(exc)}) from exc
        try:
            records = adapter.search(query, n=n, time_range=time_range)
            return records, adapter.name, warnings
        except SearchError as exc:
            warnings.append(f"{adapter.name}: {exc.code} {exc.message}")
        except Exception as exc:  # noqa: BLE001 — degraded, don't crash
            warnings.append(f"{adapter.name}: {type(exc).__name__}: {exc}")
    raise SearchError("MLS-E402", "网络不可用且无离线降级", {"warnings": warnings})


def build_query(text: str, *, lang: str = "en", extra_terms: list[str] | None = None) -> str:
    """Build a normalized search query. MICP-domain aware: adds controlled
    terms when the request is about MICP/EICP/biomineralization."""
    text = text.strip()
    if not text:
        raise ValueError("query text required")
    core = text
    # Add MICP-domain grounding when the request is clearly domain-related.
    # "ureoly" matches "ureolysis" (word-boundary-free suffix).
    domain_hint = re.search(
        r"\b(?:micp|eicp|biomineralization|biocement|microbial|enzyme|urease|urea)\b|ureoly",
        text, re.IGNORECASE)
    if domain_hint:
        extra = list(extra_terms or [])
        if not any("carbonate" in t.lower() for t in extra):
            extra.append("calcium carbonate precipitation")
        if any(k in text.lower() for k in ("urea", "urease", "ureolys")) and not any("ammonium" in t.lower() for t in extra):
            extra.append("ammonium")
        core = f"{text} {' '.join(extra)}".strip()
    return core


def repro_id(query: str, *, database: str = "auto", n: int = 10,
             time_range: tuple[int | None, int | None] = (None, None)) -> str:
    """Deterministic fingerprint of the *query* (normalized). Used for M6
    repeated-run consistency and trace logs."""
    payload = json.dumps({
        "query": normalize_query(query),
        "database": database,
        "n": n,
        "time_range": time_range,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_query(text: str) -> str:
    return " ".join(text.split()).lower()
