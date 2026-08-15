"""Lightweight structured logging for the MICP skill.

No third-party dependency. All log records are JSON lines written to stderr
(never stdout, which is reserved for protocol data). A ring buffer keeps the
last `capacity` records in memory so the service can embed them in the output
envelope's `provenance` without touching the filesystem.

The `--log-file` CLI flag can redirect to a file; the env var
OPM_LOG_LEVEL controls verbosity (debug|info|warn|error).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


class Logger:
    """JSON-lines logger with a bounded in-memory ring buffer."""

    def __init__(self, *, stream: TextIO | None = None, level: str = "info",
                 capacity: int = 64) -> None:
        self.stream = stream
        self.level = _LEVELS.get(level.lower(), 20)
        self.capacity = max(1, int(capacity))
        self._records: list[dict[str, Any]] = []
        self._ring: list[dict[str, Any]] = []
        self._seq = 0

    # -- record plumbing ------------------------------------------------
    def _record(self, level: str, event: str, **fields: Any) -> None:
        if _LEVELS.get(level, 20) < self.level:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": level,
            "event": event,
            "seq": self._seq,
            **fields,
        }
        self._seq += 1
        self._ring.append(rec)
        if len(self._ring) > self.capacity:
            self._ring.pop(0)
        if self.stream is not None:
            self.stream.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            self.stream.flush()

    def debug(self, event: str, **fields: Any) -> None:
        self._record("debug", event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._record("info", event, **fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._record("warn", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._record("error", event, **fields)

    def recent(self, n: int = 16) -> list[dict[str, Any]]:
        return list(self._ring[-n:])


def get_logger() -> Logger:
    """Shared process-level logger (module singleton, no hidden global state)."""
    # Re-created per call is fine; but to keep one ring buffer per process we
    # cache on the module. This is the single allowed global: it is the
    # transport-level logger owned by the CLI/service layer.
    global _LOGGER
    if _LOGGER is None:
        level = os.environ.get("OPM_LOG_LEVEL", "info")
        stream = sys.stderr
        _LOGGER = Logger(stream=stream, level=level)
    return _LOGGER


_LOGGER: Logger | None = None


def configure(level: str = "info", stream: TextIO | None = sys.stderr,
              capacity: int = 64) -> Logger:
    global _LOGGER
    _LOGGER = Logger(stream=stream, level=level, capacity=capacity)
    return _LOGGER
