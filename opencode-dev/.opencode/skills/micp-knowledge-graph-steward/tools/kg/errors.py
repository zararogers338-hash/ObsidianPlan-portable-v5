"""Error-code facade for the knowledge-graph steward (spec §十一.2).

Single source of truth lives in models.py (KgeErrorCode). This module
re-exports it so `from kg.errors import KgeError, KgeErrorCode` matches the
sibling-skill import style.
"""

from .models import KgeError, KgeErrorCode

__all__ = ["KgeError", "KgeErrorCode"]
