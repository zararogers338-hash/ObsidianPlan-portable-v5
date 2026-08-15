"""MICP domain extraction: text/table -> quantity candidates.

This layer turns parsed document content into *candidate* quantities. It is
deliberately mechanical and conservative:

  - Every candidate carries a locator (section/table/figure + page-ish anchor)
    so the source is always traceable.
  - Every candidate carries a provisional acquisition_mode:
      * values found in a table row   -> REPORTED_TABLE
      * values found in running text  -> REPORTED_TEXT
      * values explicitly labelled as read from a figure -> DIGITIZED_FROM_FIGURE
        (requires digitization.error_estimate)
      * values only derivable from other reported data -> CALCULATED_FROM_REPORTED_DATA
  - A number in text that is ambiguous about its unit or group is marked
    AMBIGUOUS (never guessed).
  - OD600 / CFU / cell concentration / viable ratio / urease activity are
    matched by distinct lexicons and never merged (units.classify_role).
  - No value is ever mixed across groups or time points here; group/time
    binding is attached later by the pipeline using explicit declarations.
"""

from __future__ import annotations

import re
from typing import Any

from models import PLACEHOLDER_MODES
import units


# ---------------------------------------------------------------------------
# Number + context parsing helpers
# ---------------------------------------------------------------------------

_NUM = r"[+-]?(?:\d+[\.,]?\d*|\d*[\.,]?\d+)(?:\s*[eE]\s*[+-]?\d+)?"
_NUM_RE = re.compile(_NUM)

_MEAN_ALIASES = ("mean", "average", "avg", "mean ±", "mean±", "均值", "平均")
_MEDIAN_ALIASES = ("median", "中位")
_N_ALIASES = ("n =", "n=", "n = ", "n=", "sample size", "样本量", "replicates", "triplicates",
              "number of specimens", "specimens per group")

_UNC_ALIASES = {
    "sd": ("sd", "s.d.", "standard deviation", "± sd", "标准差"),
    "se": ("se", "s.e.", "standard error", "sem", "± se", "标准误"),
    "ci": ("ci", "confidence interval", "置信区间", "95% ci"),
    "range": ("range", "范围"),
}


def parse_number(text: str) -> tuple[float | None, str]:
    """Extract the first number-like token from text. Returns (value, raw)."""
    m = _NUM_RE.search(text)
    if not m:
        return None, ""
    raw = m.group(0)
    cleaned = raw.replace(",", "").replace("−", "-").replace("−", "-")
    try:
        return float(cleaned), raw
    except ValueError:
        return None, raw


def contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(a.lower() in low for a in aliases)


# ---------------------------------------------------------------------------
# Quantity-classification lexicons (OD600 vs CFU vs urease ...)
# ---------------------------------------------------------------------------

# result-key -> (label aliases, canonical unit hint)
_RESULT_LEXICON: list[tuple[str, tuple[str, ...], str]] = [
    ("caco3_content", ("caco3", "calcium carbonate content", "precipitated caco3",
                       "caco3 content", "碳酸钙含量", "钙含量"), "percent"),
    ("calcite_conversion_rate", ("calcite conversion", "conversion rate", "calcium conversion",
                                 "conversion efficiency", "转化率"), "percent"),
    ("ucs", ("ucs", "unconfined compressive strength", "uniaxial compressive strength",
             "无侧限抗压强度", "unconfined strength", "compressive strength"), "kPa"),
    ("shear_strength", ("shear strength", "cohesion", "抗剪强度", "粘聚力"), "kPa"),
    ("modulus", ("modulus", "young's modulus", "elastic modulus", "stiffness", "弹性模量",
                 "secant modulus"), "kPa"),
    ("permeability", ("permeability", "hydraulic conductivity", "渗透系数", "渗透率",
                      "coefficient of permeability"), "m/s"),
    ("ammonia_nitrogen", ("ammonium", "nh4", "nh4+", "ammonia nitrogen", "氨氮", "铵"),
                          "g/L"),
    ("waste_liquid", ("waste liquid", "effluent", "废液", "wastewater"), "mL"),
    ("cost", ("cost", "成本", "cost per", "造价"), "CNY"),
    ("energy", ("energy", "能耗", "energy consumption"), "kJ"),
    ("uniformity_index", ("uniformity", "homogeneity", "coefficient of variation", "cv",
                          "均匀性", "均质性", "spatial uniformity"), "percent"),
    ("liquefaction_resistance", ("liquefaction", "抗液化", "cyclic resistance"), "dimensionless"),
    ("erosion_resistance", ("erosion", "抗冲刷", "erodibility"), "dimensionless"),
    ("crystal", ("crystal", "结晶", "crystal morphology", "crystal size"), "dimensionless"),
]

# biological/chemical condition-key -> label aliases. These live under
# conditions.biological / conditions.chemical in a card, NOT results. OD600
# (turbidity) and urease activity (hydrolysis rate) are distinct and never
# merged (enforced by units.classify_role / conflation guard).
_CONDITION_LEXICON: list[tuple[str, tuple[str, ...], str]] = [
    ("od600", ("od600", "od 600", "optical density", "optical density at 600",
               "od (600)", "od600nm"), "od600"),
    ("cfu", ("cfu", "cfu/ml", "cfu/ml.", "cfu/g", "cfu g-1", "colony-forming units",
             "colony forming units"), "cfu"),
    ("cell_concentration", ("cells/ml", "cells ml-1", "cell concentration", "cells per ml",
                            "cells/l", "cells/mg", "cells ml"), "cell_concentration"),
    ("viable_cell_ratio", ("viable cell", "viability", "live cell", "viable cells",
                           "活细胞", "存活率"), "viable_cell_ratio"),
    ("urease_activity", ("urease activity", "urease", "urea hydrolysis rate",
                         "ureolytic activity", "m urea", "mm urea", "mmol urea",
                         "u/od", "u/ml", "脲酶活性"), "urease_activity"),
    ("urea_conc", ("urea concentration", "urea conc", "urea", "尿素浓度"), "conc_molar"),
    ("calcium_conc", ("cacl2", "calcium chloride", "calcium concentration", "ca2+",
                      "calcium conc", "氯化钙"), "conc_molar"),
    ("mg2_conc", ("mgcl2", "mg2+", "magnesium", "magnesium concentration"), "conc_molar"),
    ("nh4_conc", ("nh4cl", "nh4+", "ammonium chloride", "ammonium concentration"), "conc_molar"),
    ("phosphate_conc", ("phosphate", "nah2po4", "k2hpo4"), "conc_molar"),
    ("initial_ph", ("initial ph", "ph value", "ph"), "dimensionless"),
    ("temperature_c", ("temperature", "incubation temperature", "cultivation temperature",
                       "培养温度"), "degC"),
    ("injection_rate", ("injection rate", "flow rate", "infusion rate", "注入速率",
                        "injection velocity"), "flow"),
]


def classify_result_key(label: str) -> str | None:
    """Map a table/column label to a results key, or None."""
    low = label.lower()
    for key, aliases, _unit in _RESULT_LEXICON:
        if any(a in low for a in aliases):
            return key
    return None


def classify_condition_key(label: str) -> str | None:
    """Map a table/column label to a biological/chemical conditions key."""
    low = label.lower()
    for key, aliases, _unit in _CONDITION_LEXICON:
        if any(a in low for a in aliases):
            return key
    return None


def condition_unit_hint(key: str) -> str | None:
    """Canonical unit hint for a condition key (e.g. od600 -> 'OD600')."""
    for k, _aliases, unit in _CONDITION_LEXICON:
        if k == key:
            return unit
    return None

_TIME_UNITS = ("h", "hr", "hour", "d", "day", "min", "s", "wk", "week", "day 7", "day 14",
               "day 21", "day 28", "d 7", "d 14", "d 28")


def classify_result_key(label: str) -> str | None:
    """Map a table/column label to a results key, or None."""
    low = label.lower()
    for key, aliases, _unit in _RESULT_LEXICON:
        if any(a in low for a in aliases):
            return key
    return None


def classify_timepoint(label: str) -> dict[str, Any] | None:
    """Parse a time-point label like 'Day 7', '7 d', '28 days', '24 h'.

    Supports both "Day 7" and "7 d" orderings, and cleans a full header like
    "Day 7 UCS (kPa)" down to the time token "Day 7". Returns
    {label, value, unit, sort_key} or None.
    """
    low = label.lower().strip()
    unit_map = {"d": "d", "day": "d", "days": "d", "week": "wk", "weeks": "wk",
                "h": "h", "hr": "h", "hour": "h", "hours": "h",
                "min": "min", "minutes": "min", "s": "s", "sec": "s"}
    scale = {"d": 1.0, "h": 24.0, "min": 1440.0, "s": 86400.0, "wk": 1.0 / 7.0}
    # "day 7" / "7 day" / "d 7" / "7 d" / "week 4"
    m = re.search(r"(\d+)\s*(d|day|days|week|weeks|h|hr|hour|hours|min|minutes|s|sec)\b", low)
    if not m:
        m = re.search(r"\b(d|day|days|week|weeks|h|hr|hour|hours|min|s)\s*(\d+)\b", low)
    if m:
        if m.group(1).isdigit():
            value, unit_token = float(m.group(1)), m.group(2)
        else:
            value, unit_token = float(m.group(2)), m.group(1)
        unit = unit_map.get(unit_token.lower(), unit_token.lower())
        # clean label: capitalize the time token ("Day 7", "24 h")
        num = int(value) if value == int(value) else value
        clean = f"Day {num}" if unit == "d" else f"{num} {unit}"
        return {"label": clean, "value": value, "unit": unit,
                "sort_key": scale.get(unit, 1.0) * value}
    return None


# ---------------------------------------------------------------------------
# Table parsing into quantity candidates
# ---------------------------------------------------------------------------

def _cell_unit(cell: str, header_label: str) -> str:
    """Try to extract a unit from a header cell like 'UCS (kPa)'."""
    m = re.search(r"\(([^)]*)\)", header_label)
    if m:
        return m.group(1).strip()
    m = re.search(r"\((.*?)\)", cell)
    if m:
        return m.group(1).strip()
    return ""


def extract_table_candidates(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one parsed table into quantity candidates.

    Each candidate:
      {result_key, value, unit, acquisition_mode, statistic_type, n,
       uncertainty_type, uncertainty_value, group_label, timepoint_label,
       locator, note}
    Candidates are NOT group-bound here (binding happens in the pipeline); a
    table row that mixes several groups is emitted as one candidate per column
    with a note that its group binding is unresolved (AMBIGUOUS group).
    """
    header = [str(h or "") for h in (table.get("header") or [])]
    rows = table.get("rows") or []
    table_id = table.get("table_id", "?")
    locator = str(table.get("source_locator") or table_id)
    caption = str(table.get("caption") or "")

    if not header:
        return [{
            "result_key": classify_result_key(caption) or "unknown",
            "value": None, "unit": "", "acquisition_mode": "NOT_REPORTED",
            "statistic_type": "unknown", "n": 0, "uncertainty_type": "none",
            "uncertainty_value": None, "group_label": None, "timepoint_label": None,
            "locator": locator, "note": "table without a parseable header",
        }]

    candidates: list[dict[str, Any]] = []
    for r_idx, row in enumerate(rows):
        cells = [str(c) if c is not None else "" for c in row]
        if len(cells) < 2:
            continue
        row_text = " ".join(cells)
        timepoint = classify_timepoint(cells[0]) or classify_timepoint(row_text[:40])
        for col_idx in range(1, min(len(cells), len(header))):
            hlabel = header[col_idx]
            key = classify_result_key(hlabel)
            is_condition = False
            if key is None:
                key = classify_condition_key(hlabel)
                is_condition = key is not None
            if key is None:
                continue
            col_timepoint = classify_timepoint(hlabel)
            cell = cells[col_idx].strip()
            cell_unit = _cell_unit(cell, hlabel)
            if not cell_unit and is_condition:
                cell_unit = condition_unit_hint(key) or ""
            if not cell or cell in ("-", "—", "n.d.", "nd", "N/A", "n/a"):
                candidates.append({
                    "result_key": key, "value": None, "unit": cell_unit,
                    "acquisition_mode": "NOT_REPORTED", "statistic_type": "unknown",
                    "n": 0, "uncertainty_type": "none", "uncertainty_value": None,
                    "group_label": cells[0] if cells[0] else None,
                    "timepoint_label": (col_timepoint["label"] if col_timepoint
                                        else (timepoint["label"] if timepoint else None)),
                    "column_index": col_idx,
                    "locator": f"{locator} row{r_idx} col{col_idx}",
                    "note": f"cell {cell!r} treated as not-reported",
                    "is_condition": is_condition,
                })
                continue
            value, raw = parse_number(cell)
            if value is None:
                continue
            # uncertainty detection: "3.5 ± 0.4", "3.5 ± 0.4 (n=6)"
            unc_type, unc_val = _uncertainty_from_cell(cell)
            n = _n_from_cell(cell)
            stat = "mean" if (contains_alias(hlabel, _MEAN_ALIASES) or unc_val is not None
                              or "±" in cell or "+/-" in cell) else \
                ("median" if contains_alias(hlabel, _MEDIAN_ALIASES) else "single_measurement")
            candidates.append({
                "result_key": key,
                "value": value,
                "unit": cell_unit,
                "acquisition_mode": "REPORTED_TABLE",
                "statistic_type": stat,
                "n": n,
                "uncertainty_type": unc_type,
                "uncertainty_value": unc_val,
                "group_label": cells[0] if cells[0] else None,
                "timepoint_label": (col_timepoint["label"] if col_timepoint
                                    else (timepoint["label"] if timepoint else None)),
                "column_index": col_idx,
                "locator": f"{locator} row{r_idx} col{col_idx}",
                "note": None,
                "is_condition": is_condition,
            })
    return candidates


def _uncertainty_from_cell(cell: str) -> tuple[str, float | None]:
    m = re.search(r"±\s*([+-]?\d+[\.,]?\d*)", cell)
    if m:
        try:
            return "sd", float(m.group(1).replace(",", ""))
        except ValueError:
            return "sd", None
    m = re.search(r"\(?(\d+[\.,]?\d*)\s*(sd|se|sem|ci)\)?", cell, re.IGNORECASE)
    if m:
        return m.group(2).lower(), float(m.group(1).replace(",", ""))
    return "none", None


def _n_from_cell(cell: str) -> int:
    m = re.search(r"[\(\[]?\s*n\s*=\s*(\d+)", cell, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\(n\s*=\s*(\d+)\)", cell, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


# ---------------------------------------------------------------------------
# Running-text candidate extraction
# ---------------------------------------------------------------------------

def _section_text(section: dict[str, Any]) -> str:
    return str(section.get("text") or "")


def extract_text_candidates(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract quantity candidates from running text (methods/results).

    Two patterns:
      A. "<label> is/was/reached/of <num> <unit>"  (result sentences)
      B. "<condition-label> <num> <unit>"          (methods: 'urea concentration 0.5 M')
    Conservative: a bare number with no unit and no nearby keyword is dropped
    or marked AMBIGUOUS. This is a heuristic pre-filter — final card assembly
    still requires explicit binding.
    """
    candidates: list[dict[str, Any]] = []
    for sec in sections:
        kind = sec.get("kind")
        text = _section_text(sec)
        if not text:
            continue
        heading = str(sec.get("heading") or "")
        locator = heading or f"section:{kind}"

        # Pattern A: verb-mediated result sentences
        for m in re.finditer(
            r"(?P<label>[A-Za-z][A-Za-z0-9_\- ]{1,40}?)\s*(?:is|was|reached|reached a|up to|of)\s+"
            rf"(?P<num>{_NUM})\s*"
            r"(?P<unit>(?:mM|M|mmol|uM|U)\s+urea\s*/\s*[A-Za-zµ°/²³0-9]+|"
            r"[A-Za-zµ°/²³%][A-Za-zµ°/²³0-9%.\-]{0,14})(?![A-Za-z0-9])",
            text, re.IGNORECASE):
            label = m.group("label").strip()
            cond_key: str | None = None
            key = classify_result_key(label)
            is_condition = False
            if key is None:
                cond_key = classify_condition_key(label)
                is_condition = cond_key is not None
                if cond_key is None:
                    cond_key = units.classify_role(label, m.group("unit"), None)
                    is_condition = cond_key is not None
            if key is None and not is_condition:
                continue
            num, _raw = parse_number(m.group("num"))
            unit = m.group("unit").strip()
            candidates.append({
                "result_key": key if key is not None else cond_key,
                "value": num, "unit": unit,
                "acquisition_mode": "REPORTED_TEXT",
                "statistic_type": "single_measurement",
                "n": 0, "uncertainty_type": "none", "uncertainty_value": None,
                "group_label": None, "timepoint_label": None,
                "locator": f"{locator}:{text[:m.start()].count(chr(10)) + 1}",
                "note": None,
                "_condition_label": label if key is None else None,
                "is_condition": is_condition,
            })

        # Pattern B: "<condition-label> <num> <unit>" in methods text
        for m in re.finditer(
            rf"(?P<label>(?:urea|Urea)\s+concentration|CaCl2\s+concentration|"
            rf"calcium\s+concentration|MgCl2\s+concentration|NH4Cl\s+concentration|"
            rf"phosphate\s+concentration|concentration)\s+(?:of\s+)?(?P<num>{_NUM})\s*"
            r"(?P<unit>[A-Za-zµ°/²³%][A-Za-zµ°/²³0-9%.\-]{0,12})",
            text, re.IGNORECASE):
            label = m.group("label").strip()
            key = classify_condition_key(label)
            if key is None:
                continue
            num, _raw = parse_number(m.group("num"))
            unit = m.group("unit").strip()
            candidates.append({
                "result_key": key, "value": num, "unit": unit,
                "acquisition_mode": "REPORTED_TEXT",
                "statistic_type": "single_measurement",
                "n": 0, "uncertainty_type": "none", "uncertainty_value": None,
                "group_label": None, "timepoint_label": None,
                "locator": f"{locator}:{text[:m.start()].count(chr(10)) + 1}",
                "note": None,
                "_condition_label": label,
                "is_condition": True,
            })
    return candidates


_CONDITION_LABELS = ("urea", "calcium", "cacl2", "cacl", "mg2", "nh4", "phosphate",
                     "concentration", "concn", "injection rate", "flow rate", "ph",
                     "temperature", "od", "od600", "cfu", "cell", "urease", "density",
                     "porosity", "specimen", "molar", "mol", "g/l", "g/l.", "curing",
                     "retention", "treatment", "cementation", "salinity")


def _is_condition_label(label: str) -> bool:
    low = label.lower().strip()
    return any(low.startswith(c) or low.endswith(c) or c in low for c in _CONDITION_LABELS)


# ---------------------------------------------------------------------------
# Candidate -> quantity shaping
# ---------------------------------------------------------------------------

def candidate_to_quantity(cand: dict[str, Any], *, group_id: str | None = None,
                          timepoint_id: str | None = None) -> dict[str, Any]:
    """Shape a candidate into a quantity dict, normalizing units and binding."""
    from quantity import reported, placeholder

    mode = cand.get("acquisition_mode", "REPORTED_TEXT")
    label_hint = cand.get("_condition_label") or cand.get("result_key")
    if mode in PLACEHOLDER_MODES or cand.get("value") is None:
        return placeholder(mode, unit=cand.get("unit") or "",
                           group_id=group_id, timepoint_id=timepoint_id,
                           sources=[{"locator": cand.get("locator", ""),
                                     "page": cand.get("locator", ""),
                                     "locator_type": "table" if mode == "REPORTED_TABLE" else "text"}],
                           note=cand.get("note"),
                           statistic_type=cand.get("statistic_type", "unknown"))
    digitization = cand.get("digitization")
    return reported(
        float(cand["value"]), cand.get("unit") or "",
        acquisition_mode=mode,
        statistic_type=cand.get("statistic_type", "mean"),
        n=cand.get("n", 0) or 0,
        n_note=cand.get("n_note"),
        uncertainty_type=cand.get("uncertainty_type", "none"),
        uncertainty_value=cand.get("uncertainty_value"),
        group_id=group_id, timepoint_id=timepoint_id,
        sources=[{"locator": cand.get("locator", ""), "page": cand.get("locator", ""),
                  "locator_type": "table" if mode == "REPORTED_TABLE" else "text"}],
        digitization=digitization,
        epistemic_tag=cand.get("epistemic_tag", "REPORTED"),
        note=cand.get("note") or label_hint,
        role=cand.get("_condition_role"),
        label=label_hint,
    )
