"""Review-expiry and supersession checker.

Determines when a conclusion must be re-reviewed: regulatory expiry, review
horizon passed, version/site/standard change, or contradicting new evidence.
Time source is injectable (ODG_TEST_CLOCK) for deterministic tests; the CLI and
service resolve it from the payload timestamp or the environment variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import OdgError, OdgErrorCode


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = value.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def resolve_now(payload: dict[str, Any] | None, env_now: str | None = None) -> datetime:
    """Resolve 'now': ODG_TEST_CLOCK env > payload timestamp > UTC now."""
    if env_now:
        parsed = parse_ts(env_now)
        if parsed is None:
            raise OdgError(
                OdgErrorCode.CLOCK_UNAVAILABLE,
                f"ODG_TEST_CLOCK is not a valid ISO timestamp: {env_now!r}",
            )
        return parsed
    payload_ts = parse_ts((payload or {}).get("timestamp"))
    if payload_ts is not None:
        return payload_ts
    return datetime.now(timezone.utc)


@dataclass
class ExpiryCheck:
    expired: bool
    reason: str
    effective_review_expiry: str | None
    triggers: list[dict]

    def to_dict(self) -> dict:
        return {
            "expired": self.expired,
            "reason": self.reason,
            "effective_review_expiry": self.effective_review_expiry,
            "triggers": self.triggers,
        }


def compute_review_expiry(
    payload: dict[str, Any],
    default_horizon_days: int = 180,
) -> str | None:
    """Pick the earliest review-expiry from explicit input, regulatory expiry,
    or the default horizon relative to the payload timestamp."""
    candidates: list[datetime] = []

    explicit = parse_ts(payload.get("review_expiry"))
    if explicit is not None:
        candidates.append(explicit)

    reg = payload.get("regulatory_status") or {}
    reg_exp = parse_ts(reg.get("expires_at"))
    if reg_exp is not None:
        candidates.append(reg_exp)

    base = resolve_now(payload)
    candidates.append(base + timedelta(days=default_horizon_days))

    earliest = min(candidates)
    return earliest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def check_expiry(payload: dict[str, Any], now: datetime | None = None) -> ExpiryCheck:
    """Evaluate whether the conclusion should be EXPIRED."""
    current_ts = now or resolve_now(payload)
    triggers: list[dict] = []

    # 1) explicit review_expiry passed
    exp = parse_ts(payload.get("review_expiry"))
    if exp is not None and exp <= current_ts:
        triggers.append({
            "type": "review_horizon_passed",
            "detail": f"review_expiry {exp.isoformat()} passed as of {current_ts.isoformat()}",
        })

    # 2) regulatory expiry
    reg = payload.get("regulatory_status") or {}
    reg_exp = parse_ts(reg.get("expires_at"))
    if reg_exp is not None and reg_exp <= current_ts:
        triggers.append({
            "type": "regulatory_expired",
            "detail": f"regulatory status expired {reg_exp.isoformat()}",
        })
    elif reg and reg.get("current") is False:
        triggers.append({"type": "regulatory_stale", "detail": "regulatory_status.current=false"})

    # 3) standard/version/site change: explicit signal in the payload
    if payload.get("context") and isinstance(payload.get("context"), dict):
        ctx = payload["context"]
        if ctx.get("standard_changed"):
            triggers.append({"type": "standard_changed", "detail": str(ctx.get("standard_changed"))})
        if ctx.get("site_changed"):
            triggers.append({"type": "site_changed", "detail": str(ctx.get("site_changed"))})
        if ctx.get("version_changed"):
            triggers.append({"type": "version_changed", "detail": str(ctx.get("version_changed"))})

    # 4) new contradicting evidence: main hypothesis refuted/contested
    hyp = payload.get("hypothesis_cards", []) or []
    if any(h.get("status") == "REFUTED" for h in hyp):
        triggers.append({"type": "hypothesis_refuted", "detail": "main hypothesis REFUTED by new evidence"})
    elif any(h.get("status") == "CONTESTED" for h in hyp):
        triggers.append({"type": "hypothesis_contested", "detail": "hypothesis CONTESTED"})

    expired = len(triggers) > 0
    reason = "; ".join(f"{t['type']}: {t['detail']}" for t in triggers) if triggers else "no expiry triggers"
    return ExpiryCheck(
        expired=expired,
        reason=reason,
        effective_review_expiry=compute_review_expiry(payload),
        triggers=triggers,
    )
