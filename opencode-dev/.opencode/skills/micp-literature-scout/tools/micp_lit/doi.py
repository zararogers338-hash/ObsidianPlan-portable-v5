"""DOI verification: structural validation + metadata consistency + forgery heuristics.

Three capability tiers:
  - offline rules  (always available): structural checks + forgery heuristics.
    Never claims "verified exists" offline — only `suspected_forged` /
    `offline_unverified`.
  - live Crossref  (network): resolves the DOI, returns publisher metadata.
  - consistency    : compares claimed metadata (title/year/container/author)
    against the resolved record and reports exact mismatches.

Deterministic in offline mode (no wall-clock inputs); live mode is best-effort
and never fabricates results.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from .models import DoiStatus

# E.g. "10.1061/(asce)gt.1943-5606.0000787", "10.1002/jctb.280520402"
_DOI_RE = re.compile(
    r"^10\.\d{4,9}/[^\s]{1,250}$",
    flags=re.IGNORECASE,
)
# Multiple slash segments after the prefix are legal (sub-prefixes) — keep permissive.
_SUBPREFIX_SLASHES_OK = True

# Regex-shaped heuristics that indicate a DOI is very likely not a real registry DOI.
_FORGERY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^10\.\d{4,9}/\s*$"), "empty suffix after slash"),
    (re.compile(r"^10\.[0-9a-f]{12,}$", re.IGNORECASE), "looks like a hex blob, not a registry DOI"),
    (re.compile(r"[<>\"'`|{}%]"), "forbidden characters"),
    (re.compile(r"^\s*doi\s*[:=]", re.IGNORECASE), "contains 'doi:' prefix instead of bare DOI"),
    # Reserved registrar prefixes that Crossref/DataCite never allocate.
    (re.compile(r"^10\.9999/", re.IGNORECASE), "reserved/unallocated registrar prefix 10.9999"),
    (re.compile(r"^10\.0000/", re.IGNORECASE), "reserved/unallocated registrar prefix 10.0000"),
)


def structural_issues(doi: str) -> list[str]:
    """Return a list of structural problems; empty list means structurally OK."""
    text = str(doi or "").strip()
    issues: list[str] = []
    if not text:
        issues.append("empty DOI")
        return issues
    if not _DOI_RE.match(text):
        issues.append("does not match ^10.\\d{4,9}/<suffix>$")
    for pattern, reason in _FORGERY_HINTS:
        if pattern.search(text):
            issues.append(reason)
    return issues


def is_structural_doi(doi: str) -> bool:
    return len(structural_issues(doi)) == 0


def normalize_doi(doi: Any) -> str:
    from .dedup import normalize_doi as _norm

    return _norm(doi)


def _fold(s: Any) -> str:
    """Lowercase + strip for comparison."""
    if s is None:
        return ""
    return str(s).strip().lower()


def title_match(claimed: str, actual: str) -> bool:
    from .dedup import normalize_title

    return normalize_title(claimed) == normalize_title(actual)


def year_match(claimed: Any, actual: Any) -> bool:
    c = str(claimed).strip() if claimed is not None else ""
    a = str(actual).strip() if actual is not None else ""
    if not c or not a:
        return True  # unknown side is not a mismatch
    return c == a


def check_consistency(claimed: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare claimed vs actual metadata; return list of mismatches.

    Each mismatch: {"field", "claimed", "actual"}.
    Only fields present on both sides are compared (unknown side ≠ mismatch).
    """
    mismatches: list[dict[str, Any]] = []
    claimed_title = claimed.get("title")
    actual_title = actual.get("title")
    if claimed_title and actual_title and not title_match(claimed_title, actual_title):
        mismatches.append({
            "field": "title",
            "claimed": claimed_title,
            "actual": actual_title,
        })
    claimed_year = claimed.get("year")
    actual_year = actual.get("year")
    if not year_match(claimed_year, actual_year):
        mismatches.append({
            "field": "year",
            "claimed": claimed_year,
            "actual": actual_year,
        })
    claimed_container = claimed.get("container") or claimed.get("journal")
    actual_container = actual.get("container") or actual.get("journal")
    if claimed_container and actual_container and _fold(claimed_container) != _fold(actual_container):
        mismatches.append({
            "field": "container",
            "claimed": claimed_container,
            "actual": actual_container,
        })
    return mismatches


class CrossrefFetcher:
    """Minimal Crossref /works/{doi} fetcher. Injectable transport for tests."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        user_agent: str = "micp-literature-scout/1.0.0 (mailto:research@example.com)",
        transport: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self._transport = transport  # injected transport(doi, timeout) -> dict|None|raise
        self._sleep = sleep or time.sleep

    def _http_get(self, url: str, timeout: float) -> Any:
        import requests

        resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def fetch(self, doi: str) -> dict[str, Any] | None:
        """Resolve a DOI via Crossref. Returns the message dict, or None if 404.

        Raises the underlying network exception (caller classifies).
        """
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        if self._transport is not None:
            return self._transport(normalized, self.timeout)
        url = f"https://api.crossref.org/works/{normalized}"
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._http_get(url, self.timeout)
            except Exception as exc:  # noqa: BLE001 — classify at caller
                last_exc = exc
                if attempt < self.retries:
                    self._sleep(min(1.0 * (2 ** attempt), 4.0))
        raise last_exc or RuntimeError("unreachable")

    @staticmethod
    def to_record(message: dict[str, Any]) -> dict[str, Any]:
        """Map a Crossref message dict into our minimal record shape."""
        title = message.get("title") or []
        container = message.get("container-title") or []
        year: Any = None
        date_parts = (message.get("published-print") or message.get("published-online")
                      or message.get("published") or {}).get("date-parts") or [[None]]
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
        return {
            "doi": message.get("DOI"),
            "title": title[0] if title else None,
            "container": container[0] if container else None,
            "year": year,
            "type": message.get("type"),
            "authors": [
                (f"{a.get('family', '')} {a.get('given', '')}".strip())
                for a in (message.get("author") or [])
            ],
        }


def _offline_verdict(doi: str) -> dict[str, Any]:
    """Offline-only verdict. Never claims verified existence."""
    text = str(doi or "").strip()
    issues = structural_issues(text)
    if issues:
        return {
            "doi": doi,
            "resolved": False,
            "status": DoiStatus.SUSPECTED_FORGED.value,
            "evidence": "offline_rule",
            "reason": "; ".join(issues),
        }
    return {
        "doi": doi,
        "resolved": False,
        "status": DoiStatus.OFFLINE_UNVERIFIED.value,
        "evidence": "offline_rule",
        "reason": "结构合法但离线无法核验存在性；请联网或用 doi.verify 实时核验",
    }


def verify_doi(
    doi: str,
    *,
    claimed: dict[str, Any] | None = None,
    online: bool = True,
    fetcher: CrossrefFetcher | None = None,
) -> dict[str, Any]:
    """Verify a single DOI.

    Returns a dict matching output.schema.json `doi_verifications` items:
      {doi, resolved, status, title, container, year, evidence}
    plus, when metadata was compared, `mismatches` (list of dicts).
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return {
            "doi": doi,
            "resolved": False,
            "status": DoiStatus.SUSPECTED_FORGED.value,
            "evidence": "offline_rule",
            "reason": "空 DOI",
        }
    if not online or fetcher is None:
        verdict = _offline_verdict(normalized)
        if claimed and verdict["status"] == DoiStatus.SUSPECTED_FORGED.value:
            verdict["mismatches"] = []
        return verdict

    try:
        message = fetcher.fetch(normalized)
    except Exception as exc:  # noqa: BLE001 — classify for caller
        return {
            "doi": normalized,
            "resolved": False,
            "status": DoiStatus.CHECK_FAILED.value,
            "evidence": "api",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    if message is None:
        return {
            "doi": normalized,
            "resolved": False,
            "status": DoiStatus.NOT_FOUND.value,
            "evidence": "api",
            "reason": "Crossref 返回 404 — DOI 未登记",
        }

    # Crossref /works/{doi} returns {status, message-type, message:{...}};
    # the canonical metadata lives in message["message"].
    inner = message.get("message", message) if isinstance(message, dict) else message
    record = CrossrefFetcher.to_record(inner) if isinstance(fetcher, CrossrefFetcher) else inner
    result: dict[str, Any] = {
        "doi": normalized,
        "resolved": True,
        "status": DoiStatus.VERIFIED.value,
        "title": record.get("title"),
        "container": record.get("container"),
        "year": record.get("year"),
        "evidence": "api",
    }
    if claimed:
        mismatches = check_consistency(claimed, record)
        if mismatches:
            result["status"] = DoiStatus.SUSPECTED_FORGED.value
            result["mismatches"] = mismatches
            result["reason"] = "元数据不一致; 疑似伪造或不准确引用"
        else:
            result["mismatches"] = []
    return result


def verify_dois(
    dois: list[str],
    *,
    claimed_map: dict[str, dict[str, Any]] | None = None,
    online: bool = True,
    fetcher: CrossrefFetcher | None = None,
) -> list[dict[str, Any]]:
    """Verify a list of DOIs; preserves input order. Never raises on one bad item."""
    normalized_claimed: dict[str, dict[str, Any]] = {}
    for key, value in (claimed_map or {}).items():
        normalized_claimed[normalize_doi(key)] = value
    results: list[dict[str, Any]] = []
    for doi in dois:
        claimed = normalized_claimed.get(normalize_doi(doi))
        results.append(verify_doi(doi, claimed=claimed, online=online, fetcher=fetcher))
    return results
