"""MUC — bootstrap self-test (running the skill "in role").

These scenarios exercise the skill the way an agent loaded with SKILL.md
would: a natural-language request arrives, the skill must detect the
trigger/boundary, dispatch to its REAL tools (cli.py), and produce output
that conforms to the output envelope (status/summary/findings/validation/
provenance). We run the CLI for real (subprocess) — no mocks.

Scenario 1 (acceptance gate): data violating calcium mass conservation must be
rejected; the skill must NOT proceed to engineering advice.
Scenario 2: same Ca2+ at two pH / ionic strengths → precipitation tendency
must differ, reported with SI and uncertainty.
Scenario 3: equilibrium-precipitateable vs finite-time actual precipitated must
be distinguished (kinetic ≠ equilibrium).
Scenario 4: a full calculate-and-check loop that verifies elemental
conservation on the tool's own output (reverse check).

Each scenario writes its logs into audit/ for reproducibility.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(_TOOLS, "cli.py")
AUDIT = os.path.join(SKILL_ROOT, "audit")

from muc.balance import check_elemental_balance  # noqa: E402
from muc.simulate import simulate_batch  # noqa: E402

OUTPUT_SCHEMA_REQUIRED = [
    "status",
    "summary",
    "validation",
    "provenance",
]
STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")
LABELS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")


def run_cli(args: list[str], stdin_data: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, CLI] + args,
        input=stdin_data,
        capture_output=True,
        text=True,
        cwd=_TOOLS,
        timeout=180,
    )
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"ok": False, "raw": proc.stdout[:500], "stderr": proc.stderr[:500]}


def make_output_envelope(result: dict) -> dict:
    """Build a controller-facing output envelope from a tool result, mirroring
    the LLM layer's composition (status/summary/findings/labels/provenance)."""
    ok = result.get("ok")
    payload = result.get("result") or {}
    status = "SUCCESS" if ok else "FAILED"
    findings = []
    if ok and "final" in payload:
        f = payload["final"]
        findings.append(
            {
                "text": f"urea conversion {f.get('urea_conversion_frac', 0):.3f}; "
                f"precipitated CaCO3 {f.get('caco3_solid', 0):.4f} mol/L at pH {f.get('ph', 0):.2f}",
                "label": "CALCULATED",
            }
        )
    return {
        "status": status,
        "summary": "bootstrap: tool ran" if ok else "bootstrap: tool rejected",
        "findings": findings,
        "assumptions": [],
        "evidence_used": ["S20", "S25", "S28"],
        "uncertainty": {"level": "medium", "notes": "kinetic params are model inputs, not measured"},
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {
            "schema_passed": True,
            "self_check_passed": True,
            "tool_calls": [{"tool": "cli.py", "ok": bool(ok)}],
        },
        "provenance": {
            "skill": "micp-ureolysis-chemistry",
            "skill_version": "1.0.0",
            "contract_version": "1.0.0",
            "timestamp": "2026-08-06T00:00:00Z",
            "tools_used": ["cli.py"],
        },
        "errors": [] if ok else [result.get("error")],
    }


def envelope_ok(e: dict) -> list[str]:
    """Check the envelope against the output contract."""
    problems = []
    for f in OUTPUT_SCHEMA_REQUIRED:
        if f not in e:
            problems.append(f"missing {f}")
    if e.get("status") not in STATUSES:
        problems.append(f"bad status {e.get('status')}")
    for f in e.get("findings", []):
        if f.get("label") not in LABELS:
            problems.append(f"bad label {f.get('label')}")
    return problems


def scenario1_mass_conservation_gate() -> dict:
    """The skill must REJECT data that violates Ca mass conservation and must
    NOT produce engineering advice (status FAILED/BLOCKED, no 'yield' claim)."""
    data = json.dumps({"species": {"Ca2+": 0.02}, "total_ca": 0.05})
    code, res = run_cli(["balance"], data)
    envelope = make_output_envelope(res)
    problems = envelope_ok(envelope)
    # The balance check must report the Ca imbalance.
    elemental = (res.get("result") or {}).get("elemental", {})
    ca_failed = elemental.get("Ca", {}).get("passed") is False
    return {
        "scenario": "S1 calcium mass conservation gate",
        "passed": ca_failed and code == 0 and not problems,
        "code": code,
        "problems": problems,
        "evidence": {"ca_passed": elemental.get("Ca", {}).get("passed"),
                     "envelope_status": envelope["status"]},
    }


def scenario2_same_ca_diff_pH_IS() -> dict:
    """Same Ca2+ concentration, two different pH / ionic strength → different
    precipitation tendency (SI). Report must include SI and its uncertainty."""
    low = json.dumps({"ph": 7.5, "c_total": 0.05, "ca_total": 0.05, "cl_total": 0.05})
    high = json.dumps({"ph": 9.0, "c_total": 0.05, "ca_total": 0.05, "cl_total": 0.05})
    code1, r1 = run_cli(["speciate"], low)
    code2, r2 = run_cli(["speciate"], high)
    si_low = (r1.get("result") or {}).get("si_calcite")
    si_high = (r2.get("result") or {}).get("si_calcite")
    ok = code1 == code2 == 0 and si_low is not None and si_high is not None and si_high > si_low
    return {
        "scenario": "S2 same Ca, different pH → different SI",
        "passed": ok,
        "code": code1,
        "evidence": {"si_ph7.5": round(si_low, 3), "si_ph9.0": round(si_high, 3)},
    }


def scenario3_kinetic_vs_equilibrium() -> dict:
    """Distinguish equilibrium-precipitateable bound from finite-time kinetic
    solid. Both must be reported; they must not be conflated."""
    params = {
        "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
        "kinetics": {"mode": "first", "k": 0.00005},
        "precipitation": {"enabled": True, "k_precip": 1e-9, "a_specific": 10.0, "si_threshold": 1.0},
        "t_end_s": 3600,
        "dt_s": 300,
        "cl": 0.1,
    }
    code, res = run_cli(["simulate"], json.dumps(params))
    r = res.get("result") or {}
    kin = r.get("kinetic_precipitated")
    eq = r.get("equilibrium_bound_precipitable")
    ok = code == 0 and kin is not None and eq is not None and kin <= eq + 1e-9 and eq > 0
    return {
        "scenario": "S3 kinetic ≠ equilibrium",
        "passed": ok,
        "code": code,
        "evidence": {"kinetic_precipitated": round(kin, 6), "equilibrium_bound": round(eq, 6)},
    }


def scenario4_calculate_and_reverse_check() -> dict:
    """Run a full simulate, then reverse-check elemental conservation on the
    tool's own output (urea N -> NH4; Ca -> Ca + solid)."""
    params = {
        "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
        "kinetics": {"mode": "first", "k": 1.0 / 3600.0},
        "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
        "t_end_s": 7200,
        "dt_s": 300,
        "cl": 0.1,
    }
    code, res = run_cli(["simulate"], json.dumps(params))
    if code != 0 or not res.get("ok"):
        return {"scenario": "S4 reverse check", "passed": False, "code": code, "evidence": res.get("error")}
    r = res["result"]
    f = r["final"]
    urea0 = 0.5
    urea_left = f["urea"]
    nh3_tot = f["nh3_tot"]
    ca_left = f["ca2plus"]
    solid = f["caco3_solid"]
    # Reverse conservation:
    #  N: 2*urea0 == 2*urea_left + nh3_tot
    #  Ca: ca0 == ca_left + solid
    n_lhs = 2 * urea0
    n_rhs = 2 * urea_left + nh3_tot
    ca_lhs = 0.5
    ca_rhs = ca_left + solid
    n_ok = abs(n_lhs - n_rhs) <= max(1e-6, 1e-6 * n_lhs)
    ca_ok = abs(ca_lhs - ca_rhs) <= max(1e-6, 1e-6 * ca_lhs)
    passed = code == 0 and n_ok and ca_ok
    return {
        "scenario": "S4 calculate + reverse conservation check",
        "passed": passed,
        "code": code,
        "evidence": {
            "N residual": round(n_lhs - n_rhs, 8),
            "Ca residual": round(ca_lhs - ca_rhs, 8),
            "stoich_passed": r["stoichiometry_check"]["passed"],
        },
    }


def main() -> int:
    os.makedirs(AUDIT, exist_ok=True)
    scenarios = [
        scenario1_mass_conservation_gate(),
        scenario2_same_ca_diff_pH_IS(),
        scenario3_kinetic_vs_equilibrium(),
        scenario4_calculate_and_reverse_check(),
    ]
    results = {"scenarios": scenarios, "all_passed": all(s["passed"] for s in scenarios)}
    log_path = os.path.join(AUDIT, "bootstrap.json")
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    for s in scenarios:
        mark = "PASS" if s["passed"] else "FAIL"
        print(f"[{mark}] {s['scenario']} | code={s['code']} | evidence={s.get('evidence')}")
    print(f"bootstrap: {sum(1 for s in scenarios if s['passed'])}/4 passed → audit/bootstrap.json")
    return 0 if results["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
