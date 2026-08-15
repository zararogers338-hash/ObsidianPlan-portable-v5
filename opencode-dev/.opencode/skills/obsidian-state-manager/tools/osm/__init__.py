"""Obsidian State Manager — core domain library.

Pure-Python implementation of the Obsidian Plan research-lifecycle state
machine with event sourcing. No third-party dependencies; everything is
offline-testable and deterministic when a clock is injected.

Layer map:
  errors.py        error code taxonomy (OSM-Exxx)
  models.py        states, event/command types, memory tiers, epistemic labels
  transition.py    transition table + guard evaluation (pure)
  store.py         event store: hash-chained JSONL, atomic append, snapshots
  recovery.py      crash / context-truncation recovery helpers
  watcher.py       staleness & contradiction analysis (pure)
  validate.py      thin schema-validation adapter (jsonschema when present)
  service.py       facade used by the CLI: validate → guard → append → snapshot
"""
