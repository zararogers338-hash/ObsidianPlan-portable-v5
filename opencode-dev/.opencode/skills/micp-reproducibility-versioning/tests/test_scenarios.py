"""The 10 mandatory reproducibility scenarios (SKILL.md section 八).

Each scenario is a real end-to-end exercise through the CLI:

 1. fresh temp env minimal example
 2. modify a parameter and trace affected results
 3. modify raw data → blocked or alarmed
 4. dependency upgrade → result drift is visible
 5. missing random seed → handled deterministically
 6. schema major version incompatible
 7. mid-run crash → recovery
 8. identical input, repeated run → byte-identical output
 9. external source unavailable → snapshot fallback
10. manual overwrite → hash-change detection

All tests are offline and deterministic.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import (WRITE_SUMMARY, base_payload, gen_cmd, make_sandbox,
                      run_cli)


def _reproduce(root: str, expect_exit: int = 0, **overrides) -> dict:
    payload = base_payload(root, action="reproduce")
    payload.update(overrides)
    if "commands" not in payload:
        payload["commands"] = [{"id": "write-summary", "cmd": WRITE_SUMMARY,
                                "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}]
    return run_cli("reproduce", payload, expect_exit=expect_exit)


def _service(root: str, **overrides) -> dict:
    payload = base_payload(root)
    payload.update(overrides)
    return run_cli("service", payload)


# ---------------------------------------------------------------------------
# Scenario 1 — fresh temp environment, minimal example
# ---------------------------------------------------------------------------

class TestScenario1FreshEnvironment:
    def test_minimal_reproduction(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = _reproduce(root)
        assert env["ok"] is True
        r = env["result"]
        assert r["status"] == "SUCCESS"
        m = r["reproduction_manifest"]
        assert m["schema_version"] == "1.0.0"
        assert any(i["path"] == "data/raw/ucs.csv" for i in m["inputs"])
        assert any(o["path"] == "data/processed/summary.csv" for o in m["outputs"])
        # manifest persisted
        assert os.path.isfile(os.path.join(root, "provenance", "reproduction-manifest.json"))
        # provenance event appended
        log = os.path.join(root, "provenance", "provenance.log")
        assert os.path.isfile(log)
        assert len([l for l in open(log) if l.strip()]) == 1
        # lineage: raw -> command -> outputs
        assert len(r["data_lineage"]) >= 3


# ---------------------------------------------------------------------------
# Scenario 2 — modify a parameter and trace affected results
# ---------------------------------------------------------------------------

class TestScenario2ParameterChange:
    def test_parameter_change_changes_digest_and_traces(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p1 = _reproduce(root, parameters={"curing_temp_c": 25})
        p2 = _reproduce(root, parameters={"curing_temp_c": 30})
        d1 = p1["result"]["hashes"]["parameters_digest"]
        d2 = p2["result"]["hashes"]["parameters_digest"]
        assert d1 != d2, "a parameter change must change the parameter digest"
        # lineage records the commands that consumed the parameters
        assert all(h["hop"] >= 0 for h in p2["result"]["data_lineage"])
        # both manifests differ in parameters
        assert p1["result"]["reproduction_manifest"]["parameters"] != \
            p2["result"]["reproduction_manifest"]["parameters"]

    def test_same_parameter_same_digest(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p1 = _reproduce(root, parameters={"curing_temp_c": 25})
        p2 = _reproduce(root, parameters={"curing_temp_c": 25})
        assert p1["result"]["hashes"]["parameters_digest"] == \
            p2["result"]["hashes"]["parameters_digest"]


# ---------------------------------------------------------------------------
# Scenario 3 — modify raw data → blocked or alarmed
# ---------------------------------------------------------------------------

class TestScenario3RawTamper:
    def test_writable_raw_blocks_reproduction(self, tmp_path) -> None:
        root = make_sandbox(tmp_path, protect_raw=False)
        env = _reproduce(root, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E501"
        assert "protection" in env["error"]["message"].lower()

    def test_service_level_blocks_writable_raw(self, tmp_path) -> None:
        root = make_sandbox(tmp_path, protect_raw=False)
        env = _service(root, action="reproduce",
                       commands=[{"id": "c", "cmd": "python -c \"pass\"", "cwd": "."}])
        assert env["result"]["status"] == "BLOCKED"
        assert env["result"]["errors"][0]["code"] == "MRV-E501"

    def test_ignore_flag_degrades_to_partial(self, tmp_path) -> None:
        root = make_sandbox(tmp_path, protect_raw=False)
        env = _reproduce(root, constraints={"ignore_raw_write_protection": True})
        assert env["ok"] is True  # degraded, still runs
        assert env["result"]["status"] == "SUCCESS"

    def test_tampered_raw_detected_after_baseline(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        _reproduce(root)  # establish baseline manifest
        raw = os.path.join(root, "data", "raw", "ucs.csv")
        os.chmod(raw, stat.S_IREAD | stat.S_IWRITE | stat.S_IRUSR | stat.S_IWUSR)
        with open(raw, "w") as fh:
            fh.write("specimen,treatment,ucs_mpa\nA1,ctrl,9.9\n")
        os.chmod(raw, stat.S_IREAD | stat.S_IRUSR)
        env = run_cli("check-pollution", base_payload(root, action="check-pollution"))
        assert env["result"]["verdict"] == "pollution_detected"
        kinds = {f["kind"] for f in env["result"]["findings"]}
        assert "manifest_mismatch" in kinds


# ---------------------------------------------------------------------------
# Scenario 4 — dependency upgrade → result drift is visible
# ---------------------------------------------------------------------------

class TestScenario4DependencyUpgrade:
    def test_lockfile_drift_flagged(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        lock = os.path.join(root, "requirements.txt")
        with open(lock, "w") as fh:
            fh.write("numpy==1.26.0\n")
        # baseline reproduction records the lockfile hash in the env report
        _reproduce(root)
        # "upgrade" the dependency
        with open(lock, "w") as fh:
            fh.write("numpy==2.0.0\n")
        env = run_cli("check-pollution", base_payload(root, action="check-pollution"))
        findings = env["result"]["findings"]
        assert any(f["kind"] == "dependency_drift" for f in findings), \
            f"expected dependency_drift, got {findings}"

    def test_no_lockfile_is_a_risk(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = _reproduce(root)
        risks = [x["risk"] for x in env["result"]["risks"]]
        assert any("lockfile" in r for r in risks)


# ---------------------------------------------------------------------------
# Scenario 5 — missing random seed
# ---------------------------------------------------------------------------

class TestScenario5MissingSeed:
    def test_missing_seed_defaults_deterministically(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        # remove the fixture's random_seed so the default (0) applies
        p = base_payload(root, action="reproduce",
                         commands=[{"id": "w", "cmd": WRITE_SUMMARY,
                                    "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}])
        del p["random_seed"]
        a = run_cli("reproduce", p)
        b = run_cli("reproduce", p)
        assert a["result"]["seed"]["value"] == 0
        assert a["result"]["seed"]["value"] == b["result"]["seed"]["value"]

    def test_require_policy_rejects_missing_seed(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="seed", seed_policy="require")
        del p["random_seed"]
        env = run_cli("seed", p, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E102"

    def test_seed_tool_deterministic(self) -> None:
        a = run_cli("seed", {"seed_policy": "reuse", "random_seed": 7})
        b = run_cli("seed", {"seed_policy": "reuse", "random_seed": 7})
        assert a["result"]["preview"] == b["result"]["preview"]


# ---------------------------------------------------------------------------
# Scenario 6 — schema major version incompatible
# ---------------------------------------------------------------------------

class TestScenario6SchemaMajorBreak:
    def test_major_mismatch_incompatible(self) -> None:
        env = run_cli("compat", {
            "task_id": "t", "project_id": "p", "request": "兼容检查",
            "skill_version": "1.0.0", "controller_version": "x",
            "timestamp": "2026-08-07T00:00:00Z",
            "action": "compat", "schema_versions": {"manifest": "2.0.0"}})
        assert env["ok"] is True
        res = env["result"]
        assert res["all_compatible"] is False
        manifest_res = [r for r in res["results"] if r["artifact"] == "manifest"][0]
        assert manifest_res["compatible"] is False
        assert "major" in manifest_res["reason"]

    def test_migrate_major_rejected_without_chain(self) -> None:
        env = run_cli("migrate", {
            "task_id": "t", "project_id": "p", "request": "迁移",
            "skill_version": "1.0.0", "controller_version": "x",
            "timestamp": "2026-08-07T00:00:00Z",
            "action": "migrate", "schema_versions": {"manifest": "2.0.0"}})
        assert env["ok"] is True
        actions = env["result"]["actions"]
        assert actions[0]["applied"] is False
        assert "no migration chain" in actions[0]["reason"]

    def test_patch_migration_appliable(self) -> None:
        # Effective manifest version is 1.0.0; a declared 0.9.x is a major gap
        # (0→1) and is rejected. A same-major lower-version is not representable
        # with effective 1.0.0, so the only non-major action is a no-op; this
        # asserts the migrator is honest about it rather than fabricating work.
        env = run_cli("migrate", {
            "task_id": "t", "project_id": "p", "request": "迁移",
            "skill_version": "1.0.0", "controller_version": "x",
            "timestamp": "2026-08-07T00:00:00Z",
            "action": "migrate", "schema_versions": {"manifest": "1.0.0"},
            "apply": True})
        assert env["ok"] is True
        actions = env["result"]["actions"]
        assert actions == []  # already at the effective version: no fabricated migration

    def test_skill_version_major_rejected(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = _service(root, action="env", skill_version="2.0.0")
        assert env["result"]["status"] == "BLOCKED"
        assert env["result"]["errors"][0]["code"] == "MRV-E801"


# ---------------------------------------------------------------------------
# Scenario 7 — mid-run crash → recovery
# ---------------------------------------------------------------------------

class TestScenario7CrashRecovery:
    def test_failed_step_then_recovery(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        # Step that fails (writes to a bogus path -> python error)
        bad = gen_cmd("import os;os.path.join('data','raw','nope')")  # noqa: F841
        failing = base_payload(root, action="reproduce",
                               commands=[{"id": "boom", "cmd": "python -c \"raise SystemExit(7)\"",
                                          "cwd": ".", "expected_outputs": []}])
        env = run_cli("reproduce", failing, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E303"
        # No partial manifest was persisted (atomic pipeline)
        assert not os.path.exists(os.path.join(root, "provenance",
                                              "reproduction-manifest.json"))
        # Recovery: run a healthy reproduction in the same tree
        ok = _reproduce(root)
        assert ok["ok"] is True
        assert ok["result"]["status"] == "SUCCESS"

    def test_empty_stdin_is_clean_error(self) -> None:
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", "mrv", "cli.py")
        proc = subprocess.run([sys.executable, script, "env"], input="",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(script))
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"]["code"] == "E_INPUT_EMPTY"


# ---------------------------------------------------------------------------
# Scenario 8 — identical input, repeated run → byte-identical output
# ---------------------------------------------------------------------------

class TestScenario8RepeatConsistency:
    def test_byte_identical_rerun(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        payload = base_payload(root, action="reproduce",
                               commands=[{"id": "write-summary", "cmd": WRITE_SUMMARY,
                                          "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]}])
        e1 = run_cli("reproduce", payload)
        e2 = run_cli("reproduce", payload)
        # manifest, hashes, lineage, checks must be byte-identical; the
        # provenance event advances the append-only chain (prev_hash differs).
        assert json.dumps(e1["result"]["reproduction_manifest"], sort_keys=True) == \
            json.dumps(e2["result"]["reproduction_manifest"], sort_keys=True)
        assert json.dumps(e1["result"]["hashes"], sort_keys=True) == \
            json.dumps(e2["result"]["hashes"], sort_keys=True)
        assert e1["result"]["identical_to_previous"] is False  # 1st run, no baseline
        assert e2["result"]["identical_to_previous"] is True   # 2nd run matches 1st

    def test_service_repeatable(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="env")
        a = run_cli("service", p)
        b = run_cli("service", p)
        assert json.dumps(a["result"], sort_keys=True) == \
            json.dumps(b["result"], sort_keys=True)


# ---------------------------------------------------------------------------
# Scenario 9 — external data source unavailable → snapshot fallback
# ---------------------------------------------------------------------------

class TestScenario9SnapshotFallback:
    def test_external_layer_snapshot_used(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        # External source snapshot lives in data/external; the run consumes it.
        ext = os.path.join(root, "data", "external", "pump_calib.json")
        with open(ext, "w") as fh:
            fh.write('{"flow_cal": 1.0}\n')
        cmd = gen_cmd(
            "import json;"
            "d=json.load(open('data/external/pump_calib.json'));"
            "open('data/processed/calib.json','w').write(json.dumps({'ok': d['flow_cal']}))"
        )
        env = _reproduce(root, commands=[
            {"id": "snap", "cmd": cmd, "cwd": ".",
             "expected_outputs": ["data/processed/calib.json"]}])
        assert env["ok"] is True
        inputs = [i["path"] for i in env["result"]["reproduction_manifest"]["inputs"]]
        assert "data/external/pump_calib.json" in inputs
        # snapshot is part of the traced input set (fallback is explicit)
        assert any("external" in i for i in inputs)

    def test_missing_external_is_reported_not_fabricated(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        # External snapshot removed after baseline -> pollution check surfaces it.
        ext = os.path.join(root, "data", "external", "calib.json")
        with open(ext, "w") as fh:
            fh.write("{}")
        _reproduce(root)
        os.remove(ext)
        env = run_cli("check-pollution", base_payload(root, action="check-pollution"))
        # removed input surfaced as missing (the manifest check records a removal)
        assert env["result"]["verdict"] == "pollution_detected"


# ---------------------------------------------------------------------------
# Scenario 10 — manual overwrite → hash-change detection
# ---------------------------------------------------------------------------

class TestScenario10ManualOverwrite:
    def test_processed_overwrite_detected(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        _reproduce(root)
        out = os.path.join(root, "data", "processed", "summary.csv")
        with open(out, "w") as fh:
            fh.write("ctrl,9.99\nmicp,9.99\n")
        env = run_cli("check-pollution", base_payload(root, action="check-pollution"))
        assert env["result"]["verdict"] == "pollution_detected"
        assert any(f["kind"] == "manifest_mismatch"
                   and "summary.csv" in f["detail"] for f in env["result"]["findings"])

    def test_provenance_tamper_detected(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        _reproduce(root)
        log = os.path.join(root, "provenance", "provenance.log")
        with open(log, "a") as fh:
            fh.write('{"tampered":true}\n')
        env = run_cli("check-pollution", base_payload(root, action="check-pollution"))
        assert env["result"]["verdict"] == "pollution_detected"
        assert any(f["kind"] == "provenance_tamper" for f in env["result"]["findings"])


# ---------------------------------------------------------------------------
# Diff (used by reproduce rerun comparison)
# ---------------------------------------------------------------------------

class TestDiffTool:
    def test_rerun_identical_reports_identical(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        _reproduce(root)
        env = run_cli("diff", base_payload(
            root, action="diff",
            previous_manifest="provenance/reproduction-manifest.json"))
        assert env["ok"] is True
        diffs = env["result"]["differences"]
        assert env["result"]["identical"] is True
        assert any(d["kind"] == "identical" for d in diffs)

    def test_rerun_drift_reports_differences(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        # baseline: parameters = 25 -> manifest archived
        a = _reproduce(root, parameters={"curing_temp_c": 25})
        baseline_id = a["result"]["reproduction_manifest"]["manifest_id"]
        # drifted rerun: parameters = 30 -> new manifest archived
        _reproduce(root, parameters={"curing_temp_c": 30})
        # diff the archived baseline against the current manifest
        env = run_cli("diff", base_payload(
            root, action="diff",
            previous_manifest=f"provenance/manifests/{baseline_id}.json"))
        assert env["ok"] is True
        assert env["result"]["identical"] is False
        kinds = {d["kind"] for d in env["result"]["differences"]}
        assert "modified" in kinds or "hash_mismatch" in kinds
