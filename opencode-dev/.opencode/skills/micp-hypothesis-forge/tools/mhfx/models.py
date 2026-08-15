"""Shared domain model for micp-hypothesis-forge.

Holds the epistemic vocabulary, falsifiability / refutation logic, mechanism
chain normalization, and DAG utilities shared by every tool. Offline,
deterministic, stdlib-only.
"""

from __future__ import annotations

import math
import re
from typing import Any

# ---------------------------------------------------------------------------
# Epistemic labels (Obsidian Plan spec §六)
# ---------------------------------------------------------------------------

EPISTEMIC_LABELS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")

# HYPOTHESIS / INFERRED / RECOMMENDATION may never be presented as OBSERVED.
_STRONGEST_ALLOWED = {
    "OBSERVED": "OBSERVED",
    "REPORTED": "REPORTED",
    "CALCULATED": "CALCULATED",
    "INFERRED": "INFERRED",      # stronger than OBSERVED? No: inference from evidence.
    "HYPOTHESIS": "HYPOTHESIS",  # not yet supported by measurement.
    "RECOMMENDATION": "RECOMMENDATION",
}

# Order of epistemic strength (weak -> strong). Used to guard against
# mislabeling a weaker claim as a stronger one.
EPISTEMIC_STRENGTH = {"HYPOTHESIS": 0, "INFERRED": 1, "RECOMMENDATION": 2,
                      "CALCULATED": 3, "REPORTED": 4, "OBSERVED": 5}


def is_epistemic(label: str) -> bool:
    return label in EPISTEMIC_LABELS


def validate_label(label: str) -> None:
    if not is_epistemic(label):
        from .errors import MhfxError, MhfxErrorCode
        raise MhfxError(MhfxErrorCode.EPISTEMIC_MISLABEL,
                        f"Unknown epistemic label {label!r}; expected one of {EPISTEMIC_LABELS}.",
                        detail={"label": label, "allowed": list(EPISTEMIC_LABELS)})


# ---------------------------------------------------------------------------
# Falsifiability / refutation logic
# ---------------------------------------------------------------------------

# Subjective markers that indicate a statement may be non-falsifiable.
_VAGUE_MARKERS = (
    "probably", "may", "might", "could be related", "plays a role",
    "has an effect", "is important", "contributes", "influences", "associated",
)
_NEGATION_MARKERS = ("not", "no ", "never", "does not", "cannot", "won't")


def refutation_classification(refutation: str) -> dict:
    """Classify a refutation condition by its observable grounding.

    Returns a dict with:
      - text        : normalized text
      - has_observable : whether it names a measurable quantity (number, %, rate,
                         concentration, unit symbols, etc.)
      - has_direction  : whether it states a directional change (rise/fall/above/below)
      - has_threshold  : whether it names a numeric threshold
      - ambiguous      : whether it is too vague to adjudicate (probably/might/...)
      - verdict        : FALSIFIABLE | PARTIALLY_FALSIFIABLE | NOT_FALSIFIABLE
      - reason         : human-readable reason
    """
    if not refutation or not refutation.strip():
        return {"text": "", "has_observable": False, "has_direction": False,
                "has_threshold": False, "ambiguous": True,
                "verdict": "NOT_FALSIFIABLE",
                "reason": "Refutation condition is empty: nothing can contradict it."}

    text = " ".join(refutation.split()).lower()
    has_number = bool(re.search(r"\d", text))
    has_unit_marker = bool(re.search(r"(%)|(mol/l)|(molar)|(mm)|(cm)|(mpa)|(kpa)|(m/s)|(mg)|(g/l)|(ppm)|(conc\.?)|(rate)|(u/cs)|(temperature)|(days?)|(hours?)", text))
    has_observable = has_number or has_unit_marker
    has_direction = bool(re.search(r"(increase|decrease|rise|fall|above|below|exceed|less than|greater than|higher|lower|faster|slower|double|halve|>|<|≥|≤)", text))
    has_threshold = has_number
    ambiguous = any(m in text for m in _VAGUE_MARKERS)

    if not has_observable:
        return {"text": text, "has_observable": False, "has_direction": has_direction,
                "has_threshold": has_threshold, "ambiguous": ambiguous,
                "verdict": "NOT_FALSIFIABLE",
                "reason": "No observable quantity is named — nothing can be measured to test it."}
    if ambiguous:
        return {"text": text, "has_observable": True, "has_direction": has_direction,
                "has_threshold": has_threshold, "ambiguous": True,
                "verdict": "PARTIALLY_FALSIFIABLE",
                "reason": "An observable is named but hedged with vague language; reframe with a concrete predicted value or direction."}
    if not has_direction:
        return {"text": text, "has_observable": True, "has_direction": False,
                "has_threshold": has_threshold, "ambiguous": False,
                "verdict": "PARTIALLY_FALSIFIABLE",
                "reason": "An observable is named but no predicted direction/threshold is given; state what would count as support vs refutation."}
    return {"text": text, "has_observable": True, "has_direction": True,
            "has_threshold": has_threshold, "ambiguous": False,
            "verdict": "FALSIFIABLE",
            "reason": "Names an observable quantity with a directional prediction — measurable and testable."}


def is_falsifiable(statement: str, refutation: str) -> dict:
    """Full falsifiability verdict for a hypothesis statement + refutation condition.

    Returns {"falsifiable": bool, "verdict": ..., "reason": ..., "checks": {...}}.
    A hypothesis with no refutation condition is automatically NON-FALSIFIABLE.
    """
    stmt_ok = bool(statement and statement.strip())
    if not stmt_ok:
        return {"falsifiable": False, "verdict": "NOT_FALSIFIABLE",
                "reason": "Hypothesis statement is empty.",
                "checks": {"statement_present": False, "refutation_present": False}}

    cls = refutation_classification(refutation)
    verdict = cls["verdict"]
    return {
        "falsifiable": verdict == "FALSIFIABLE",
        "verdict": verdict,
        "reason": cls["reason"],
        "checks": {"statement_present": True,
                   "refutation_present": bool(refutation and refutation.strip()),
                   "has_observable": cls["has_observable"],
                   "has_direction": cls["has_direction"],
                   "has_threshold": cls["has_threshold"],
                   "ambiguous": cls["ambiguous"]},
    }


# ---------------------------------------------------------------------------
# Mechanism chains
# ---------------------------------------------------------------------------

def normalize_chain(chain: Any) -> list[str]:
    """Normalize a mechanism chain to a list of non-empty steps."""
    if chain is None:
        return []
    if isinstance(chain, str):
        # Accept "A -> B -> C", "A → B → C", "A ⇒ B", or "A, B, C"
        text = chain.replace("→", "->").replace("⇒", "->").replace(",,", ",")
        parts = re.split(r"\s*->\s*|,\s*", text.strip())
        return [p.strip() for p in parts if p.strip()]
    if isinstance(chain, list):
        return [str(p).strip() for p in chain if str(p).strip()]
    raise TypeError("mechanism_chain must be a string or list of strings")


def chain_min_length(chain: Any, minimum: int) -> bool:
    """A mechanism chain must have >= minimum causal steps (default 2: cause -> effect)."""
    return len(normalize_chain(chain)) >= minimum


# ---------------------------------------------------------------------------
# DAG utilities (used by dag.py and competing-matrix.py)
# ---------------------------------------------------------------------------

def topo_sort(nodes: list[dict]) -> list[str]:
    """Kahn topological order of node ids. Raises ValueError on cycle."""
    ids = {n["id"] for n in nodes}
    edges: dict[str, set[str]] = {nid: set() for nid in ids}
    indeg: dict[str, int] = {nid: 0 for nid in ids}
    for n in nodes:
        nid = n["id"]
        for dep in n.get("depends_on", []) or []:
            if dep not in ids:
                raise ValueError(f"unknown dependency {dep!r} of {nid!r}")
            edges[dep].add(nid)
            indeg[nid] += 1
    ready = [nid for nid in ids if indeg[nid] == 0]
    order: list[str] = []
    while ready:
        ready.sort()
        nid = ready.pop(0)
        order.append(nid)
        for m in sorted(edges[nid]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    if len(order) != len(ids):
        remaining = [nid for nid in ids if indeg[nid] > 0]
        raise ValueError(f"cycle detected among: {remaining}")
    return order


def ancestors(nodes: list[dict], node_id: str) -> set[str]:
    """All transitive ancestors of node_id (excluding itself)."""
    by_id = {n["id"]: n for n in nodes}
    seen: set[str] = set()

    def walk(nid: str) -> None:
        for dep in by_id[nid].get("depends_on", []) or []:
            if dep not in seen:
                seen.add(dep)
                if dep in by_id:
                    walk(dep)
    if node_id not in by_id:
        raise KeyError(node_id)
    walk(node_id)
    return seen


def descendants(nodes: list[dict], node_id: str) -> set[str]:
    """All transitive descendants of node_id (excluding itself)."""
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[str]] = {nid: [] for nid in by_id}
    for n in nodes:
        for dep in n.get("depends_on", []) or []:
            if dep in by_id:
                children[dep].append(n["id"])
    out: set[str] = set()
    stack = list(children[node_id])
    while stack:
        nid = stack.pop()
        if nid not in out:
            out.add(nid)
            stack.extend(children[nid])
    return out


# ---------------------------------------------------------------------------
# Numeric discipline helpers (score normalization, information gain)
# ---------------------------------------------------------------------------

def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def entropy(p: float) -> float:
    """Binary entropy in bits; p is clamped to (0,1)."""
    p = clamp01(p)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def expected_information_gain(prior_p: float, sensitivity: float, specificity: float) -> float:
    """EIG of a binary discriminating test given prior P(hypothesis true).

    sensitivity  = P(positive | hypothesis true)
    specificity  = P(negative | hypothesis false)
    Returns expected reduction in binary entropy (bits). Clamped to [0,1].
    """
    p = clamp01(prior_p)
    sens = clamp01(sensitivity)
    spec = clamp01(specificity)

    # P(positive) = P(+|H)P(H) + P(+|~H)(1-P(H))  ; P(+|~H) = 1 - specificity
    p_pos = sens * p + (1 - spec) * (1 - p)
    if p_pos <= 0.0 or p_pos >= 1.0:
        return 0.0
    # posterior P(H|positive)
    p_h_pos = sens * p / p_pos
    # posterior P(H|negative)
    p_neg = 1 - p_pos
    p_h_neg = (1 - sens) * p / p_neg if p_neg > 0 else p
    h_prior = entropy(p)
    h_pos = entropy(p_h_pos)
    h_neg = entropy(p_h_neg)
    eig = h_prior - (p_pos * h_pos + p_neg * h_neg)
    return clamp01(eig)


# Urea-hydrolysis stoichiometric fact (CALCULATED, not OBSERVED — spec §七).
# CO(NH2)2 + CaCl2 + 2 H2O -> CaCO3 + 2 NH4Cl : per mol CaCO3 (~100 g),
# ~2 mol NH4+ (~36 g N) produced when hydrolysis is complete.
UREOLYSIS_STOICHIOMETRY_NOTE = (
    "per mole CaCO3 precipitated via the ureolytic pathway, ~2 mol NH4+ "
    "(~36 g N as ammonium) are produced — CALCULATED from stoichiometry, "
    "not OBSERVED. Non-ureolytic pathways must NOT inherit the urea model."
)
