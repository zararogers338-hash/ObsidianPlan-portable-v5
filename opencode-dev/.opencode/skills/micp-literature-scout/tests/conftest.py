"""Shared pytest fixtures for micp-literature-scout.

Keeps tests offline by default (SkillService(offline=True)); injects a fixed
clock (MLS_TEST_CLOCK is honored by the service `now` injection) so determinism
tests are byte-stable.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make tools/ importable from tests without installation.
TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

FIXED_TS = "2026-08-06T12:00:00.000Z"


def fixed_clock() -> object:
    return lambda: datetime.fromisoformat("2026-08-06T12:00:00+00:00")


@pytest.fixture
def fixed_now():
    return fixed_clock()


@pytest.fixture
def base_payload() -> dict:
    return {
        "contract_version": "1.0",
        "task_id": "test-task",
        "project_id": "test-proj",
        "request": "检索 MICP 均匀性文献证据",
        "skill_version": "1.0.0",
        "controller_version": "1.0",
        "timestamp": FIXED_TS,
        "human_approval_state": {"granted": True},
    }
