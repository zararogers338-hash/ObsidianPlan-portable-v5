"""Ontology helpers (spec §四.1): default MICP ontology and vocabulary access.

Re-exports the base ontology builder from io so modules and tools have one
import surface.
"""

from .io import base_ontology, generate_ontology_schema, validate_against_ontology

__all__ = ["base_ontology", "generate_ontology_schema", "validate_against_ontology"]
