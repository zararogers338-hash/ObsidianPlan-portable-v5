"""Strain identity verification and biosafety classification.

The auditor NEVER defaults a strain to safe because it is commonly used in
MICP. Every strain must carry a verifiable identity (taxonomy, provenance,
culture-collection accession) and an explicit biosafety assessment.

An unknown / unverifiable strain is a hard gate (MBS-E203) that leads to
HUMAN_APPROVAL_REQUIRED upstream.
"""

from __future__ import annotations

from typing import Any

from .errors import MbsError, MbsErrorCode

# Strains/patterns that are frequently used in MICP literature. This is NOT a
# safety verdict — it is a registry the auditor uses to ask sharper questions
# and to demand evidence. Nothing here overrides the biosafety classification
# that a named, depository-verified strain actually carries.
COMMON_MICP_STRAIN_HINTS = {
    "sporosarcina pasteurii": {
        "notes": "Most-studied MICP strain. Widely regarded as a safe/GRAS-adjacent soil bacterium (BSL-1 in most national lists).",
        "verify_via": "ATCC 11859 / DSM 33 / NCIMB 8841; check the organism's biosafety classification in the national list actually in force at the site.",
    },
    "sporosarcina ureae": {
        "notes": "Ureolytic soil bacterium, closely related to S. pasteurii.",
        "verify_via": "Depository accession + national biosafety list.",
    },
    "bacillus subtilis": {
        "notes": "GRAS-classified food/soil bacterium in many jurisdictions; still verify site-relevant classification.",
        "verify_via": "Depository accession + national biosafety list.",
    },
    "bacillus licheniformis": {
        "notes": "Used in some MICP work; check the site-relevant biosafety classification.",
        "verify_via": "Depository accession + national biosafety list.",
    },
    "lysinibacillus": {
        "notes": "Ureolytic strains used in biostimulation/converged communities; verify species-level identity.",
        "verify_via": "Species-level identification + national biosafety list.",
    },
    "sulfobacillus": {
        "notes": "Acidophilic; not typical of standard urea-MICP. Confirm pathway before assuming ureolysis.",
        "verify_via": "Species-level identification.",
    },
}

# Pathogen risk groups commonly cited for bacteria: RG-1 (unlikely to cause
# human disease), RG-2 (moderate individual risk). These labels MUST be
# reconciled with the national pathogen list at the site.
RISK_GROUP_RULES = {
    "rg1": {"label": "RG-1", "human_pathogenicity": "unlikely to cause disease in healthy adults", "biosafety_level": "BSL-1"},
    "rg2": {"label": "RG-2", "human_pathogenicity": "may cause disease; unlikely to spread", "biosafety_level": "BSL-2"},
    "rg3": {"label": "RG-3", "human_pathogenicity": "serious disease; effective treatment available", "biosafety_level": "BSL-3"},
    "rg4": {"label": "RG-4", "human_pathogenicity": "serious disease; no effective treatment", "biosafety_level": "BSL-4"},
}

PATHOGENIC_GENUS_MARKERS = [
    "staphylococcus", "streptococcus", "pseudomonas", "klebsiella", "salmonella",
    "shigella", "escherichia", "vibrio", "bacillus anthracis", "listeria",
    "clostridium", "legionella", "mycobacterium", "brucella",
]


def verify_strain_identity(strain: dict[str, Any] | None) -> dict[str, Any]:
    """Verify a strain description carries a usable identity.

    A strain is `verified` only when it has a name AND (a culture-collection
    accession OR a resolvable provenance). Without those, the auditor cannot
    trust any biosafety classification (MBS-E203).
    """
    if not isinstance(strain, dict) or not strain:
        raise MbsError(
            MbsErrorCode.STRAIN_IDENTITY_UNKNOWN,
            "No strain provided. An auditor cannot assess biosafety of an "
            "unidentified organism; obtain strain identity before proceeding.",
            detail={"field": "strain"},
        )
    name = str(strain.get("name") or strain.get("id") or "").strip()
    accession = str(strain.get("culture_collection_id") or strain.get("accession") or "").strip()
    source = str(strain.get("source") or strain.get("provenance") or "").strip()
    if not name:
        raise MbsError(
            MbsErrorCode.STRAIN_IDENTITY_UNKNOWN,
            "Strain name/id is missing. Identity cannot be verified.",
            detail={"field": "strain.name"},
        )
    verified = bool(accession) or bool(source)
    hint = None
    lower = name.lower()
    for key in COMMON_MICP_STRAIN_HINTS:
        if key in lower:
            hint = COMMON_MICP_STRAIN_HINTS[key]
            break
    # Pathogenic-genus flag (never a verdict alone — only a demand for evidence).
    pathogenic_marker = any(m in lower for m in PATHOGENIC_GENUS_MARKERS)
    return {
        "verified": verified,
        "name": name,
        "accession": accession,
        "source": source,
        "common_micp_hint": hint,
        "pathogenic_marker": pathogenic_marker,
        "needs_regulatory_check": True,  # national biosafety list must still be checked at site
    }


def classify_biosafety(
    strain: dict[str, Any],
    *,
    site_pathogen_list_ref: str | None = None,
    claimed_risk_group: str | None = None,
) -> dict[str, Any]:
    """Biosafety classification for a verified strain.

    Rules:
    - Unknown identity -> unclassifiable (caller must gate HUMAN_APPROVAL).
    - A claimed risk_group that is not among the valid labels is rejected.
    - A pathogenic genus marker with no site evidence -> classified as needing
      BSL-2+ evidence; cannot be defaulted to BSL-1.
    - Without a site pathogen-list reference the classification is provisional
      and flagged `needs_regulatory_confirmation: True`.
    """
    identity = verify_strain_identity(strain)
    name = identity["name"]
    pathogenic_marker = identity.get("pathogenic_marker", False)
    if not identity["verified"]:
        return {
            "name": name,
            "identity_verified": False,
            "biosafety_level": None,
            "risk_group": None,
            "classification_confidence": "none",
            "needs_regulatory_confirmation": True,
            "pathogenic_marker": pathogenic_marker,
            "provisional": True,
            "reason": "Identity unverifiable; biosafety cannot be classified.",
        }

    # Resolve claimed risk group.
    rg = None
    if claimed_risk_group:
        key = claimed_risk_group.lower()
        if key not in RISK_GROUP_RULES:
            raise MbsError(
                MbsErrorCode.INPUT_SCHEMA_VIOLATION,
                f"claimed_risk_group '{claimed_risk_group}' not in {sorted(RISK_GROUP_RULES)}.",
                detail={"field": "claimed_risk_group"},
            )
        rg = RISK_GROUP_RULES[key]

    # Pathogenic marker forces at least BSL-2 evidence.
    if identity["pathogenic_marker"] and (rg is None or rg["biosafety_level"] == "BSL-1"):
        rg = RISK_GROUP_RULES["rg2"]  # demand BSL-2 evidence; do not default safe

    site_confirmed = bool(site_pathogen_list_ref)
    if rg is None:
        # No claimed risk group: default to provisional BSL-1 ONLY when the site
        # pathogen list is referenced (the institutional committee assessed it).
        # Without a site reference this is NOT a safety verdict.
        if site_confirmed:
            return {
                "name": name,
                "identity_verified": True,
                "biosafety_level": "BSL-1",
                "risk_group": "RG-1",
                "classification_confidence": "confirmed",
                "needs_regulatory_confirmation": False,
                "pathogenic_marker": pathogenic_marker,
                "provisional": False,
                "reason": "BSL-1 per site pathogen-list assessment (non-pathogen, "
                          "institutional biosafety committee confirmed against the "
                          "in-force national list).",
            }
        return {
            "name": name,
            "identity_verified": True,
            "biosafety_level": "BSL-1",  # provisional working level only
            "risk_group": "RG-1",
            "classification_confidence": "provisional",
            "needs_regulatory_confirmation": True,
            "pathogenic_marker": pathogenic_marker,
            "provisional": True,
            "reason": "No site pathogen-list reference provided; provisional BSL-1 "
                      "working assumption that MUST be confirmed against the "
                      "national biosafety list at the site.",
        }
    return {
        "name": name,
        "identity_verified": True,
        "biosafety_level": rg["biosafety_level"],
        "risk_group": rg["label"],
        "classification_confidence": "confirmed" if site_confirmed else "provisional",
        "needs_regulatory_confirmation": not site_confirmed,
        "pathogenic_marker": pathogenic_marker,
        "provisional": not site_confirmed,
        "reason": f"Classified {rg['label']} / {rg['biosafety_level']} "
                  f"{'per site pathogen list' if site_confirmed else 'per claimed risk group; site list still required'}.",
    }
