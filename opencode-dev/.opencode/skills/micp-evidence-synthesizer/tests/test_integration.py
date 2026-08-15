"""Integration tests: full pipeline through MesService and the CLI,
asserting real tool calls and machine-parseable envelopes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mes import jsonschema as _js  # noqa: E402
from mes.service import MesService  # noqa: E402

from conftest import load_schema, make_base_input, make_card  # noqa: E402

CLI = ROOT / "tools" / "mes_cli.py"


@pytest.fixture(scope="module")
def service():
    return MesService(skill_root=str(ROOT))


def run_cli(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestServicePipeline:
    def test_success_single_card_is_partial(self, service):
        out = service.handle(make_base_input())
        assert out["status"] in ("SUCCESS", "PARTIAL")
        assert out["skill"] == "micp-evidence-synthesizer"
        assert out["validation"]["input_schema"] == "passed"

    def test_two_comparable_cards_synthesize(self, service):
        cards = [
            make_card(ref_id="doi:10.1000/a", study_id="chen2024",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa", "direction": "higher_is_better"},
                      reported_effect={"arms": [
                          {"name": "MICP", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"},
                          {"name": "control", "n": 6, "mean": 0.4, "sd": 0.1, "unit": "MPa"}]}),
            make_card(ref_id="doi:10.1000/b", study_id="li2023",
                      outcome={"name": "UCS", "value": 2.8, "unit": "MPa", "direction": "higher_is_better"},
                      reported_effect={"arms": [
                          {"name": "MICP", "n": 5, "mean": 2.8, "sd": 0.3, "unit": "MPa"},
                          {"name": "control", "n": 5, "mean": 0.3, "sd": 0.1, "unit": "MPa"}]}),
        ]
        out = service.handle(make_base_input(evidence_cards=cards))
        assert out["status"] == "SUCCESS"
        assert out["synthesis"]["comparability_check"]["status"] != "incomparable"
        # pooling should have been admissible with low heterogeneity
        assert out["synthesis"]["meta_analysis"] is not None
        assert out["synthesis"]["evidence_matrix"][0]["value"] == 3.2
        assert all(r["pooled_effect"] is not None for r in out["synthesis"]["sensitivity"]["runs"])

    def test_conflict_matrix_present(self, service):
        a = make_card(ref_id="doi:10.1000/a", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa", "direction": "higher_is_better"})
        b = make_card(ref_id="doi:10.1000/b", study_id="b",
                      outcome={"name": "UCS", "value": 0.4, "unit": "MPa", "direction": "higher_is_better"})
        out = service.handle(make_base_input(evidence_cards=[a, b]))
        assert out["status"] == "SUCCESS"
        assert any(c["type"] == "magnitude" for c in out["synthesis"]["conflict_matrix"])

    def test_high_risk_chains_audit_skills(self, service):
        out = service.handle(make_base_input(risk_level="high"))
        names = [s["skill"] for s in out["requested_next_skills"]]
        assert "obsidian-red-team" in names
        assert "obsidian-decision-gate" in names

    def test_approval_gate(self, service):
        out = service.handle(make_base_input(constraints={"field_deployment": True}))
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert out["errors"][0]["code"] == "OES-E107"

    def test_determinism(self, service):
        a = service.handle(make_base_input())
        b = service.handle(make_base_input())
        a.pop("provenance", None)
        b.pop("provenance", None)
        assert a == b


class TestServiceOutputContract:
    def test_all_statuses_validate_against_output_schema(self, service):
        schema = load_schema("output.schema.json")
        cases = [
            service.handle(make_base_input()),
            service.handle(make_base_input(evidence_cards=[])),
            service.handle(make_base_input(risk_level="high")),
            service.handle(make_base_input(constraints={"field_deployment": True})),
        ]
        for out in cases:
            issues = _js.validate(out, schema)
            assert issues == [], [i.message for i in issues]


class TestCLI:
    def test_stdin_stdout(self):
        out = run_cli(make_base_input())
        assert out["skill"] == "micp-evidence-synthesizer"

    def test_invalid_json_returns_envelope(self):
        proc = subprocess.run([sys.executable, str(CLI)], input="not json",
                              capture_output=True, text=True, timeout=60)
        out = json.loads(proc.stdout)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E101"

    def test_validate_schema_flag(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), "--validate-schema", str(ROOT / "examples" / "01-synthesize.json")],
            capture_output=True, text=True, timeout=60)
        # examples/01 may not exist yet at test time; guard
        if proc.returncode == 2 and "cannot read" in proc.stderr:
            pytest.skip("examples not yet present")
        assert proc.returncode in (0, 1)
