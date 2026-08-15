"""micp-experiment-designer toolset package.

Deterministic, offline, stdlib-first Python tools for designing MICP /
biocementation experiments from a Hypothesis Card: DOE & power analysis,
randomization, quantity/unit math, SOP generation & checking, preregistration
templates, and JSON Schema validation.

Run any tool via `python -m tools.cli` with a JSON envelope on stdin, or
invoke a tool module directly: `python tools/doe_power.py`.
"""

__all__ = [
    "cli",
    "doe_power",
    "randomizer",
    "quantity_calc",
    "sop_check",
    "preregister",
    "validate",
    "unit_validate",
    "jsonschema_subset",
    "_common",
]
