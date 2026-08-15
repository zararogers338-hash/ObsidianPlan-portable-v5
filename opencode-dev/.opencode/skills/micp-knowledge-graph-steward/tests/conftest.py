"""Shared pytest fixtures. Run with: python -m pytest tests/ -q"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS_DIR / "knowledge_graph_steward.py"

BASE = {
    "contract_version": "1.0",
    "task_id": "t-unit",
    "project_id": "unit-project",
    "request": "unit test invocation",
    "action": None,
    "skill_version": "1.0.0",
    "timestamp": "2026-08-06T00:00:00Z",
}


def build_store(request: pytest.FixtureRequest) -> tempfile.TemporaryDirectory:
    """One temp store per test to keep integration tests isolated."""
    td = tempfile.TemporaryDirectory(prefix="kge_store_")
    request.addfinalizer(td.cleanup)
    return td


def cli_call(store: str, action: str, *, overrides: dict | None = None,
             extra: dict | None = None, expect_ok: bool = True) -> dict:
    payload = dict(BASE)
    if overrides:
        payload.update(overrides)
    payload["action"] = action
    if extra:
        payload.update(extra)
    proc = subprocess.run(
        [sys.executable, str(CLI), "--store", store],
        input=json.dumps(payload), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"CLI crashed: {proc.stderr}"
    out = json.loads(proc.stdout)
    if expect_ok:
        assert out["status"] not in ("FAILED", "BLOCKED", "NEED_ADDITIONAL_SKILL"), (
            f"unexpected non-success for {action}: {out.get('summary')} errors={out.get('errors')}"
        )
    return out


@pytest.fixture
def store_root() -> str:
    td = tempfile.TemporaryDirectory(prefix="kge_store_")
    yield td.name
    td.cleanup()


@pytest.fixture
def svc(store_root):
    sys.path.insert(0, str(TOOLS_DIR))
    from kg.service import KnowledgeGraphService

    return KnowledgeGraphService(store_root)


@pytest.fixture
def cli(store_root):
    return store_root


# A stock knowledge base that has been initialized once.
@pytest.fixture
def ready_base(cli) -> str:
    cli_call(cli, "kb.init", extra={"title": "fixture"})
    return cli
