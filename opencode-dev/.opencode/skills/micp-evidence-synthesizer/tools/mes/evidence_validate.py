"""Evidence Card validation + traceability (OES-E102, OES-E109)."""

from __future__ import annotations

from typing import Any

from .errors import MesError, MesErrorCode
from .models import EVIDENCE_LEVELS, LABELS, LAYERS, RISK_OF_BIAS_LEVELS, stable_digest

_REQUIRED_CARD_FIELDS = ("ref_id", "study_id", "study_type", "outcome", "evidence_level")
_STUDY_TYPES = {
    "randomized_trial", "quasi_experiment", "cohort", "case_series",
    "lab_experiment", "field_experiment", "review", "modeling", "other",
}


def _finite_number(value: Any, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"{label} must be a number, got {type(value).__name__}")
    if value != value:  # NaN
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"{label} is NaN")
    if value in (float("inf"), float("-inf")):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"{label} is infinite")


def validate_card(card: dict, ref_id_hint: str = "?") -> list[str]:
    """Validate a single Evidence Card. Returns list of human-readable problems.

    Never raises for bad data; returns problems so the caller can aggregate.
    Structural misuse (non-dict) raises MesError — that is a protocol fault.
    """
    problems: list[str] = []
    if not isinstance(card, dict):
        raise MesError(MesErrorCode.EVIDENCE_UNVERIFIABLE,
                       f"card for ref {ref_id_hint} is not an object")
    for f in _REQUIRED_CARD_FIELDS:
        if f not in card:
            problems.append(f"missing required card field '{f}'")
        elif card[f] is None or (isinstance(card[f], str) and card[f] == ""):
            problems.append(f"card field '{f}' is empty")

    ref_id = card.get("ref_id", ref_id_hint)

    # traceability: ref_id must look resolvable (DOI/URI/archive style)
    rid = str(ref_id).strip()
    if len(rid) < 3:
        problems.append("ref_id too short to be a verifiable reference")
    elif not any(m in rid for m in ("doi", "10.", "http", "arxiv", "zenodo", ":", "/")):
        problems.append("ref_id does not look like a verifiable identifier (DOI/URI/archive)")

    st = card.get("study_type")
    if st is not None and st not in _STUDY_TYPES:
        problems.append(f"study_type '{st}' not in {sorted(_STUDY_TYPES)}")

    el = card.get("evidence_level")
    if el is not None and el not in EVIDENCE_LEVELS:
        problems.append(f"evidence_level '{el}' not in {EVIDENCE_LEVELS}")

    layer = card.get("layer")
    if layer is not None and layer not in LAYERS:
        problems.append(f"layer '{layer}' not in {LAYERS}")

    rob = ((card.get("risk_of_bias") or {}).get("overall")) if isinstance(card.get("risk_of_bias"), dict) else None
    if rob is not None and rob not in RISK_OF_BIAS_LEVELS:
        problems.append(f"risk_of_bias.overall '{rob}' not in {RISK_OF_BIAS_LEVELS}")

    # numeric sanity: outcome + arms
    outcome = card.get("outcome")
    if isinstance(outcome, dict):
        try:
            _finite_number(outcome.get("value"), f"card {rid} outcome.value")
            _finite_number(outcome.get("spread", {}).get("sd"), f"card {rid} outcome.spread.sd")
        except MesError as exc:
            problems.append(exc.message)

    arms = ((card.get("reported_effect") or {}).get("arms")) if isinstance(card.get("reported_effect"), dict) else None
    if isinstance(arms, list):
        seen_names: set[str] = set()
        for i, arm in enumerate(arms):
            if not isinstance(arm, dict):
                problems.append(f"card {rid} reported_effect.arms[{i}] not an object")
                continue
            name = arm.get("name")
            if not name:
                problems.append(f"card {rid} arms[{i}] missing name")
            elif name in seen_names:
                problems.append(f"card {rid} arms[{i}] duplicate arm name '{name}'")
            seen_names.add(name)
            for f in ("n", "mean", "unit"):
                if f not in arm:
                    problems.append(f"card {rid} arms[{i}] missing '{f}'")
            try:
                _finite_number(arm.get("n"), f"card {rid} arms[{i}].n")
                _finite_number(arm.get("mean"), f"card {rid} arms[{i}].mean")
                _finite_number(arm.get("sd"), f"card {rid} arms[{i}].sd")
                _finite_number(arm.get("se"), f"card {rid} arms[{i}].se")
            except MesError as exc:
                problems.append(exc.message)
            n = arm.get("n")
            if isinstance(n, (int, float)) and (n < 1 or n != int(n)):
                problems.append(f"card {rid} arms[{i}].n must be a positive integer")

    # claims labels must be epistemic labels
    claims = card.get("claims")
    if isinstance(claims, list):
        for i, claim in enumerate(claims):
            if isinstance(claim, dict) and claim.get("label") not in LABELS:
                problems.append(f"card {rid} claims[{i}].label not in {LABELS}")

    # dry-run style conflicts list
    conflicts = card.get("conflicts_with")
    if isinstance(conflicts, list):
        for c in conflicts:
            if not isinstance(c, str) or c == rid:
                problems.append(f"card {rid} conflicts_with entry invalid (self-reference or non-string)")

    return problems


def validate_cards(cards: list) -> dict:
    """Validate a card list. Returns {'ok': bool, 'problems': list[str], 'ref_ids': set}."""
    if not isinstance(cards, list) or len(cards) == 0:
        raise MesError(MesErrorCode.INPUT_SCHEMA, "evidence_cards must be a non-empty array")
    problems: list[str] = []
    ref_ids: set[str] = set()
    seen: dict[str, int] = {}
    for i, card in enumerate(cards):
        probs = validate_card(card, f"card[{i}]")
        problems.extend(f"card[{i}] {p}" for p in probs)
        rid = (card or {}).get("ref_id")
        if isinstance(rid, str):
            seen[rid] = seen.get(rid, 0) + 1
            ref_ids.add(rid)
    dupes = [rid for rid, count in seen.items() if count > 1]
    for rid in dupes:
        problems.append(f"duplicate ref_id '{rid}' (traceability broken)")
    return {"ok": len(problems) == 0, "problems": problems, "ref_ids": ref_ids}


def card_digest(card: dict) -> str:
    """Content digest of a card for audit chains (independent of ref_id)."""
    return stable_digest(card)
