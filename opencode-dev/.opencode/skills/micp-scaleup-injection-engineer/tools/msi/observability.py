"""Observability: deterministic logger for micp-scaleup-injection-engineer."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Logger:
    def __init__(self) -> None:
        self._records: list[dict] = []

    def info(self, msg: str, **fields) -> None:
        self._records.append({"level": "info", "msg": msg, "ts": now_iso(), **fields})

    def warn(self, msg: str, **fields) -> None:
        self._records.append({"level": "warn", "msg": msg, "ts": now_iso(), **fields})

    def recent(self, n: int = 12) -> list[dict]:
        return self._records[-n:]


_logger: Logger | None = None


def get_logger() -> Logger:
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def configure(level: str = "info") -> Logger:
    # level is accepted for CLI symmetry; the logger keeps all records.
    return get_logger()
