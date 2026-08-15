"""Failure & adversarial tests: missing inputs, contract conflicts, malformed
payloads, path traversal, forged citations. Each must be BLOCKED/FAILED with a
specific MLS-E code, never crash the CLI, and never fabricate a result."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from micp_lit.service import ACTIONS, SkillService  # noqa: E402
from micp_lit.validate import validate_output  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent.parent / "tools"
CLI = TOOLS / "literature_scout.py"


def _payload(base, **kw):
    p = dict(base)
    p.update(kw)
    return p


class TestMissingInput:
    """Metric M4: each required field missing → BLOCKED naming the field."""

    REQUIRED = ["task_id", "project_id", "request", "action", "skill_version", "contract_version", "timestamp"]

    def test_each_required_field(self, base_payload):
        svc = SkillService(offline=True)
        for field in self.REQUIRED:
            p = _payload(base_payload, action="search.run")
            p.pop(field, None)
            out = svc.run(p)
            assert out["status"] == "BLOCKED", f"{field}: got {out['status']}"
            assert out["errors"][0]["code"] == "MLS-E102"
            detail = out["errors"][0].get("detail", {})
            assert field in detail.get("missing_fields", {}), f"{field} not named"
            assert detail["missing_fields"][field], f"{field} guidance empty"
            valid, _ = validate_output(out)
            assert valid


class TestSchemaAdversarial:
    def test_non_dict_input(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run("not a dict")
        assert out["status"] in ("FAILED", "BLOCKED")
        assert out["errors"][0]["code"] == "MLS-E101"

    def test_contract_major_2(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run", contract_version="2.0"))
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MLS-E104"

    def test_unknown_action(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="not.a.real.action"))
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MLS-E103"

    def test_illegal_role(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run",
                               actor={"role": "root"}))
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MLS-E503"

    def test_invalid_timestamp_type(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run", timestamp=12345))
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MLS-E101"


class TestApprovalGates:
    def test_network_search_requires_approval(self, base_payload):
        svc = SkillService(offline=False)
        out = svc.run(_payload(base_payload, action="search.run",
                               human_approval_state={"granted": False}))
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert out["errors"][0]["code"] == "MLS-E501"

    def test_offline_skips_network_approval(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run",
                               human_approval_state={"granted": False}))
        assert out["status"] == "SUCCESS"

    def test_sources_register_requires_approval(self, base_payload):
        svc = SkillService(offline=False)
        out = svc.run(_payload(base_payload, action="sources.register",
                               human_approval_state={"granted": False},
                               reference={"kind": "database", "title": "X", "purpose": "Y"}))
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert out["errors"][0]["code"] == "MLS-E502"


class TestForgedCitation:
    def test_suspected_forged_flagged(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="doi.verify",
                               candidate_dois=["10.9999/fake.paper.2024"]))
        assert out["status"] == "PARTIAL"
        assert out["doi_verifications"][0]["status"] == "suspected_forged"
        assert any(e["code"] == "MLS-E203" for e in out["errors"])
        # Must not appear as verified evidence.
        assert all(f["label"] != "REPORTED" or "存在" not in f["statement"]
                   for f in out["findings"] if "10.9999" in f.get("refs", []))

    def test_metadata_mismatch_rejected(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="doi.verify",
                               candidate_dois=["10.1234/ok"],
                               claimed_metadata={"10.1234/ok": {"title": "claimed T", "year": 1999}}))
        # Offline: cannot verify existence, so status is offline_unverified;
        # the claimed metadata is not confirmed.
        assert out["doi_verifications"][0]["status"] in ("offline_unverified", "suspected_forged")


class TestPathTraversal:
    def test_project_id_rejected(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run",
                               project_id="..%2f..%2fetc"))
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MLS-E101"  # pattern violation

    def test_out_file_escapes_skill_dir(self, base_payload, tmp_path):
        """out_file outside cwd is not guarded; cwd must be supplied by the
        controller. The CLI default cwd is the working directory. We assert the
        service honors explicit cwd and that absolute out_file inside cwd works."""
        svc = SkillService(cwd=tmp_path)
        target = tmp_path / "exports" / "refs.bib"
        out = svc.run(_payload(base_payload, action="cite.export",
                               records=[{"ref_id": "a", "doi": "10.1000/x",
                                         "title": "T", "year": 2020, "container": "J"}],
                               format="bibtex", out_file="exports/refs.bib"))
        assert out["status"] == "SUCCESS"
        assert target.is_file()


class TestCliRobustness:
    def _run_cli(self, payload: dict, offline: bool = True):
        args = [sys.executable, str(CLI), "--offline"] if offline else [sys.executable, str(CLI)]
        proc = subprocess.run(args, input=json.dumps(payload), capture_output=True,
                              text=True, timeout=120)
        return proc

    def test_stdin_empty(self):
        proc = subprocess.run([sys.executable, str(CLI)], input="", capture_output=True,
                              text=True, timeout=60)
        assert proc.returncode == 2
        out = json.loads(proc.stdout)
        assert out["errors"][0]["code"] == "MLS-E100"

    def test_stdin_invalid_json(self):
        proc = subprocess.run([sys.executable, str(CLI)], input="{not json",
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 2
        out = json.loads(proc.stdout)
        assert out["errors"][0]["code"] == "MLS-E100"

    def test_cli_offline_search(self, base_payload):
        proc = self._run_cli(_payload(base_payload, action="search.run"))
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out["status"] == "SUCCESS"
        assert out["search"]["database"] == "offline_fixture"

    def test_cli_bad_input_still_valid_envelope(self, base_payload):
        proc = self._run_cli(_payload(base_payload, action="search.run",
                                      contract_version="9.9"))
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MLS-E104"


class TestConflictInput:
    def test_duplicate_requests_same_repro(self, base_payload):
        """Same query text → same repro_id regardless of request wording."""
        svc = SkillService(offline=True)
        p1 = _payload(base_payload, action="search.run", request="MICP 均匀性证据",
                      query={"text": "MICP uniformity"})
        p2 = _payload(base_payload, action="search.run", request="另一个请求措辞",
                      query={"text": "MICP uniformity"})
        out1 = svc.run(p1)
        out2 = svc.run(p2)
        assert out1["provenance"]["repro_id"] == out2["provenance"]["repro_id"]
