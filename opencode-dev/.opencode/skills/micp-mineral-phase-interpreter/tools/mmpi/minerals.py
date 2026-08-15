"""Mineral phase reference knowledge base for MICP carbonate interpretation.

This module is the single source of truth for *reference data* used by every
tool in this skill: XRD fingerprint peaks, crystal morphology, FTIR/Raman
bands, and phase metadata. It contains only widely reported reference values
that are cross-checked against the sources listed in
``references/sources.md``; where a number is approximate or contested, the
``uncertainty`` field says so. The module NEVER fabricates values: if a datum
cannot be sourced it is simply not listed.

Reference values below follow the convention of quantitative XRD on carbonate
polymorphs: calcite (trigonal R-3c), aragonite (orthorhombic Pnam), vaterite
(hexagonal P63/mmc, sometimes reported as P63/m) and amorphous calcium
carbonate (ACC, no long-range order).

Peaks are listed as (d_spacing_Angstrom, hkl, relative_intensity_pct). The
2theta columns are *informative* for Cu K-alpha 1.540598 A and are computed,
never authoritative; the d-spacing is the primary fingerprint.

Confidence legend used across this skill:
  primary   = diagnostic on its own for the polymorph
  secondary = supportive only; needs corroboration
  conflict  = peak commonly overlaps with another carbonate phase
"""

from __future__ import annotations

# Cu K-alpha1 wavelength in Angstrom (CODATA / NIST standard for X-ray tubes).
CU_KALPHA1_A = 1.540598

# Mineral phase registry. `shortname` is the machine-safe phase id used in
# input/output envelopes and in evidence labels.
MINERAL_PHASES: dict[str, dict] = {
    "calcite": {
        "shortname": "calcite",
        "formula": "CaCO3",
        "system": "trigonal (rhombohedral), space group R-3c",
        "morphology": [
            "rhombohedral cleavage rhombs (104 habit)",
            "euhedral rhombohedra or scalenohedra when unconfined",
            "blocky, faceted crystals",
            "equant / sub-rounded when growing in confined pore space",
        ],
        "xrd": [
            # (d_spacing_A, hkl, relative_intensity_pct, confidence)
            (3.86, (0, 1, 2), 12, "secondary"),
            (3.035, (1, 0, 4), 100, "primary"),
            (2.495, (1, 1, 0), 14, "secondary"),
            (2.285, (1, 1, 3), 18, "secondary"),
            (2.095, (2, 0, 2), 18, "secondary"),
            (1.927, (0, 2, 4), 5, "secondary"),
            (1.875, (0, 1, 8), 17, "secondary"),
            (1.626, (1, 1, 6), 4, "secondary"),
        ],
        "ftir": {
            "transmittance": [
                # (wavenumber_cm1, assignment, confidence)
                (712, "v4 in-plane CO3 bending", "primary"),
                (874, "v2 out-of-plane CO3 bending", "primary"),
                (1430, "v3 asymmetric CO3 stretch (broad)", "primary"),
            ],
            "notes": "Diagnostic carbonate bands at ~712/874/1430 cm-1; splitting of "
                     "the ~1430 band into ~1390/1480 is a calcite/aragonite ordering marker.",
        },
        "raman": [
            (1086, "v1 symmetric CO3 stretch", "primary"),
            (712, "v4 CO3 bending", "secondary"),
            (283, "lattice mode", "secondary"),
        ],
        "tga": {
            "decomposition_temperature_c": 600,
            "decomp_range_c": [540, 780],
            "mass_loss_wt_pct": 43.97,
            "notes": "CaCO3 -> CaO + CO2. 43.97 wt% is the stoichiometric CO2 loss; "
                     "observed loss lower than stoichiometric can indicate residual ACC, "
                     "organic matter, or partially dehydrated material.",
        },
    },
    "aragonite": {
        "shortname": "aragonite",
        "formula": "CaCO3",
        "system": "orthorhombic, space group 62; Pmcn setting (a=4.9618 b=7.9691 c=5.7429, "
                   "ICDD PDF 41-1475; Pmcn in Sanjuan 2019; Pnam in some older compilations — "
                   "same group, different setting)",
        "notes": "Cell params verified against COD entry 2100187 (Acta Cryst. B 2005) and "
                 "Sanjuan et al. 2019 (Sep. Purif. Technol. 211:857-865).",
        "morphology": [
            "acicular / needle-like crystals",
            "spicular, radiating fans or bundles",
            "bladed aggregates",
            "prismatic columns",
        ],
        "xrd": [
            (3.396, (1, 1, 1), 100, "primary"),
            (3.273, (0, 2, 1), 52, "secondary"),
            (2.70, (1, 0, 2), 46, "secondary"),
            (2.481, (2, 0, 0), 33, "secondary"),
            (2.372, (2, 0, 1), 38, "secondary"),
            (2.341, (1, 1, 2), 31, "secondary"),
            (1.977, (2, 2, 0), 65, "secondary"),
            (1.881, (2, 1, 1), 42, "secondary"),
            (1.812, (1, 0, 3), 23, "secondary"),
        ],
        "ftir": {
            "transmittance": [
                (700, "v4 CO3 bending (split 700/713)", "primary"),
                (713, "v4 CO3 bending (split 700/713)", "primary"),
                (854, "v2 CO3 bending (aragonite marker)", "primary"),
                (1083, "v1 symmetric stretch", "secondary"),
                (1475, "v3 asymmetric stretch", "secondary"),
            ],
            "notes": "FTIR diagnostic: strong sharp 854 cm-1 with the 700/713 doublet is "
                     "characteristic of aragonite, vs the single 712 + 874 set of calcite.",
        },
        "raman": [
            (1086, "v1 symmetric CO3 stretch", "primary"),
            (704, "v4 CO3 bending", "secondary"),
            (208, "lattice mode", "secondary"),
        ],
        "tga": {
            "decomposition_temperature_c": 800,
            "decomp_range_c": [790, 830],
            "mass_loss_wt_pct": 43.97,
            "notes": "Aragonite is metastable at room pressure/temperature and converts to "
                     "calcite; TGA decomposition overlaps calcite so TGA alone cannot "
                     "distinguish the two polymorphs.",
        },
    },
    "vaterite": {
        "shortname": "vaterite",
        "formula": "CaCO3",
        "system": "hexagonal (PDF 33-0268, P63/mmc a=7.1473 c=16.917) — COMPETING structures "
                   "exist (C2/c, Mugnaioli 2012 COD 1508970; P6(2)22 supercell, Wang & Becker 2009). "
                   "hkl indexing must be treated with caution; d-spacing matching is primary.",
        "morphology": [
            "spherulitic aggregates",
            "spherical or lens-like particles",
            "flattened disks, 'rosettes'",
            "often polycrystalline spheroids (SEM)",
        ],
        "xrd": [
            # PDF 33-0268 (P63/mmc). NOTE (sources.md §关键结论): vaterite cell
            # parameters vary between compilations (COD 9007475 gives a=4.13 c=8.49,
            # giving (110) at ~3.50 A; PDF 33-0268 gives ~3.57 A). The (110) d
            # range is therefore [3.50, 3.58] — matched as an interval, not a
            # point, because vaterite peak positions drift with hydration and
            # ordering. Per-peak intensity ordering is approximate.
            (3.57, (1, 1, 0), 100, "primary"),
            (3.29, (1, 1, 2), 25, "secondary"),
            (2.73, (1, 1, 4), 30, "secondary"),
            (2.06, (1, 0, 8), 35, "secondary"),
            (1.85, (1, 1, 0), 40, "secondary"),
        ],
        "xrd_interval_overrides": {
            # (phase_key, ref_d) -> (lo, hi) in Angstrom. vaterite (110) drifts
            # with hydration/ordering; accept the observed 3.50-3.58 family.
            (3.57, (1, 1, 0)): (3.50, 3.58),
        },
        "notes": "vaterite peak positions drift (hydration/ordering); (110) family at "
                 "3.50-3.58 A is matched as an interval. See references/sources.md.",
        "ftir": {
            "transmittance": [
                (745, "v4 CO3 bending (vaterite marker ~745)", "primary"),
                (877, "v2 CO3 bending", "secondary"),
                (1087, "v1 symmetric stretch (vaterite marker)", "secondary"),
                (1490, "v3 asymmetric stretch, broad/split", "secondary"),
            ],
            "notes": "vaterite FTIR: 745 cm-1 peak (and broad ~1490) differentiates from "
                     "calcite (712) and aragonite (700/713 doublet + 854).",
        },
        "raman": [
            (1090, "v1 symmetric CO3 stretch", "primary"),
            (740, "v4 CO3 bending", "secondary"),
            (300, "lattice mode", "secondary"),
        ],
        "tga": {
            "decomposition_temperature_c": 700,
            "decomp_range_c": [600, 800],
            "mass_loss_wt_pct": 43.97,
            "notes": "Vaterite is the least thermodynamically stable crystalline polymorph; "
                     "hydrates (CaCO3.nH2O) decompose at lower temperature than anhydrous forms.",
        },
    },
    "acc": {
        "shortname": "acc",
        "formula": "CaCO3.nH2O (hydrated)",
        "system": "amorphous (no long-range order)",
        "morphology": [
            "smooth, featureless spheroids or films",
            "no crystal faces",
            "sometimes colloidal aggregates (SEM)",
        ],
        "xrd": {
            "pattern": "broad hump centered ~2theta 29-30 (Cu Ka); no sharp reflections",
            "notes": "Presence of ACC is diagnosed by ABSENCE of sharp reflections plus a "
                     "broad amorphous halo; quantify via Rietveld amorphous content or by "
                     "comparing observed vs calculated crystalline mass.",
        },
        "ftir": {
            "transmittance": [
                (866, "v2 CO3 (broad, shifted vs calcite)", "secondary"),
                (1400, "v3 broad, poorly split", "secondary"),
            ],
            "notes": "ACC shows broad, poorly resolved carbonate bands vs the sharp splitting "
                     "of crystalline polymorphs; exact position depends on hydration state.",
        },
        "raman": [
            (1080, "v1 CO3 broad/weak", "secondary"),
        ],
        "tga": {
            "decomposition_temperature_c": 550,
            "decomp_range_c": [200, 650],
            "mass_loss_wt_pct": "variable (nH2O + CO2)",
            "notes": "ACC loses structural water <200 C then CO2 ~550-650 C; TGA mass-loss "
                     "steps can help bound ACC content but water-loss overlap with organics "
                     "limits precision.",
        },
    },
}

# Detection-agnostic diagnostic summary used in the fusion scorer.
# confidence: how strongly each modality alone can identify the phase.
PHASE_DIAGNOSTICS: dict[str, dict] = {
    "calcite": {
        "xrd": "primary: 3.035 A (104) sharp reflection",
        "ftir": "primary: 712+874+1430; single 874",
        "raman": "primary: sharp 1086",
        "sem_morphology": "secondary: rhombohedral habit (morphology is suggestive, not diagnostic)",
        "eds": "supporting: Ca ~ CaCO3 stoichiometry (Ca:CO3 cannot be measured directly)",
    },
    "aragonite": {
        "xrd": "primary: 3.396 A (111) + 1.977 A (220)",
        "ftir": "primary: 854 + 700/713 doublet",
        "raman": "primary: 1086 + weak 704",
        "sem_morphology": "secondary: acicular needles",
        "eds": "supporting: Ca signal only",
    },
    "vaterite": {
        "xrd": "primary: 3.57 A (110) + 3.29 A (112)",
        "ftir": "primary: 745 + broad 1490",
        "raman": "primary: 1090",
        "sem_morphology": "secondary: spherulitic",
        "eds": "supporting: Ca signal only",
    },
    "acc": {
        "xrd": "primary (by absence): amorphous halo, no sharp peaks",
        "ftir": "secondary: broad carbonate bands",
        "raman": "secondary: broad weak v1",
        "sem_morphology": "secondary: smooth spheroids",
        "eds": "supporting: Ca signal only",
    },
}

# Diagnostic spectral bands that are SPECIFIC to one polymorph (spec §五:
# "哪些证据相互支持/哪些证据冲突"). A shared band (e.g. ~712/713 v4 doublet,
# ~1086 v1) is common to several carbonates and must NOT count as corroboration
# for a specific phase. Only *co-occurring marker groups* may corroborate phase
# identity, and every band in a group must be present:
#   calcite    [712, 874]: v4 single + v2. The v4 712 alone is NOT diagnostic —
#              aragonite's v4 doublet (700/713) overlaps at the 6 cm-1 tolerance,
#              so 712-713 cannot separate calcite from aragonite. 874 (calcite v2)
#              sits 20 cm-1 from aragonite 854, so requiring 874 disambiguates.
#   aragonite  [854, 700] and [854, 713]: v2 + either v4 member. 854 is the
#              strongest marker; requiring a v4 member too blocks a lone 854 hit.
#   vaterite   [745]: v4 marker ~40 cm-1 from calcite/aragonite, safe alone.
#   acc        none is polymorph-diagnostic (broad, poorly split).
DIAGNOSTIC_FTIR_BANDS: dict[str, list[list[float]]] = {
    "calcite": [[712.0, 874.0]],
    "aragonite": [[854.0, 700.0], [854.0, 713.0]],
    "vaterite": [[745.0]],
    "acc": [],
}

# Raman v1 (~1086-1090) is common to all crystalline polymorphs; the lattice
# modes (~208/283/300) are weak and matrix-dependent. No Raman band is treated
# as polymorph-diagnostic by this skill; Raman corroboration stays supporting.
DIAGNOSTIC_RAMAN_BANDS: dict[str, list[float]] = {p: [] for p in MINERAL_PHASES}

# Phase-to-phase transformation guidance (thermodynamic stability, wet MICP conditions).
# Source: Ostwald step rule + standard carbonate literature (see references/sources.md).
TRANSFORMATIONS: list[dict] = [
    {
        "from": "acc",
        "to": "vaterite",
        "condition": "hydrated amorphous phase crystallizes to least stable anhydrous polymorph",
        "confidence": "established",
    },
    {
        "from": "vaterite",
        "to": "calcite",
        "condition": "dissolution-recrystallization to the thermodynamically stable polymorph",
        "confidence": "established",
    },
    {
        "from": "aragonite",
        "to": "calcite",
        "condition": "aragonite is metastable at room T/P and reverts to calcite over time or heat",
        "confidence": "established",
    },
]

# Diagnostic rules that forbid over-claiming.
# Each rule: (short_name, statement) — consumed by the self-check auditor.
HARD_RULES: list[tuple[str, str]] = [
    (
        "single_sem_no_homogeneity",
        "不得仅凭单张 SEM 图像宣布整体均匀;局部晶桥观测不得外推到整体样品。",
    ),
    (
        "morphology_not_diagnostic",
        "SEM 晶体形貌只是支持性证据;不能仅凭形貌鉴定晶型(需 XRD/FTIR/Raman 交叉确认)。",
    ),
    (
        "phase_needs_evidence",
        "鉴定晶型必须说明所用证据与置信度;不得把无证据的晶型断言写成 OBSERVED。",
    ),
    (
        "local_bridge_no_global_strength",
        "颗粒接触处观测到晶桥不得直接推导宏观强度因果;需力学验证(上游 geotechnical 能力)。",
    ),
    (
        "no_fabrication",
        "不得制造引用、数据、实验结果或已完成的性能验证。",
    ),
    (
        "calcium_not_caco3",
        "EDS 检出 Ca 只证明存在含钙相,不证明是 CaCO3,更不证明是特定晶型。",
    ),
]
