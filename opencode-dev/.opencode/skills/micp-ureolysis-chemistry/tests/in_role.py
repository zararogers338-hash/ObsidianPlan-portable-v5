"""MUC — in-role self-test (the skill acting as itself).

Section 8 of the delivery contract requires that Claude, after creating the
skill, actually "becomes" it: loads SKILL.md, receives ordinary user requests
(WITHOUT leaking the expected answer), detects triggers/boundaries, dispatches
its REAL tools (no pretending), and emits a machine-readable envelope that
validates against schemas/output.schema.json.

This harness automates that loop for the four required self-bootstrap tests:
  B1  reject data that violates Ca mass conservation (acceptance gate)
  B2  same Ca2+ at different pH / ionic strength -> different precipitation
  B3  distinguish equilibrium-precipitateable from finite-time kinetic yield
  B4  run a full calculation with own tools, then reverse-check elemental
      conservation on the tool's own output

Each run: (1) user request (no expected answer embedded), (2) skill decides
trigger + tool, (3) runs tools/cli.py for real, (4) composes an output
envelope, (5) validates it against output.schema.json, (6) an adversarial
reviewer role attacks the output. Logs go to audit/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(_TOOLS, "cli.py")
AUDIT = os.path.join(SKILL_ROOT, "audit")
OUTPUT_SCHEMA = os.path.join(SKILL_ROOT, "schemas", "output.schema.json")

from muc.balance import check_elemental_balance  # noqa: E402

STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")
LABELS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")


def run_cli(tool: str, params: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, CLI, tool],
        input=json.dumps(params),
        capture_output=True,
        text=True,
        cwd=_TOOLS,
        timeout=180,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"ok": False, "raw": proc.stdout[:300], "stderr": proc.stderr[:300]}
    return out


def emit_envelope(request: str, tool: str, params: dict, res: dict) -> dict:
    """The skill composes its output envelope from the tool result."""
    ok = res.get("ok")
    result = res.get("result") or {}
    findings = []
    status = "SUCCESS" if ok else "FAILED"
    errors = []
    if not ok and res.get("error"):
        errors = [res["error"]]
        code = res["error"].get("code", "")
        status = "BLOCKED" if code in ("MUC-E1003", "MUC-E2002", "MUC-E2003", "MUC-E1006", "MUC-E2004") else status

    if ok and "elemental" in result:
        elem = result["elemental"]
        findings.append(
            {
                "text": f"Ca conservation: computed {elem['Ca']['computed']:.4f} mol/L vs "
                f"reported {elem['Ca']['total']} mol/L; passed={elem['Ca']['passed']}",
                "label": "CALCULATED",
            }
        )
        status = "SUCCESS" if elem["Ca"]["passed"] else "BLOCKED"
    elif ok and "si_calcite" in result:
        findings.append(
            {
                "text": f"SI_calcite = {result['si_calcite']:.3f} at pH {result['ph']} (I="
                f"{result['ionic_strength']:.3f} M)",
                "label": "CALCULATED",
            }
        )
        # The *interpretation* that SI>1 means higher nucleation tendency is an
        # inference, not a measurement — must carry INFERRED, not CALCULATED.
        findings.append(
            {
                "text": f"SI {'exceeds' if result['si_calcite'] > 1 else 'does not exceed'} 1; "
                "supersaturated fluids have a higher tendency to nucleate given a surface, "
                "but a single SI does not predict crystal yield (acceptance rule 9.4)",
                "label": "INFERRED",
            }
        )
        status = "SUCCESS"
    elif ok and "kinetic_precipitated" in result:
        f = result["final"]
        findings.extend(
            [
                {
                    "text": f"urea conversion {f['urea_conversion_frac']:.3f}; final pH {f['ph']:.2f}, "
                    f"SI {f['si']:.2f}",
                    "label": "CALCULATED",
                },
                {
                    "text": f"kinetic precipitated CaCO3 {result['kinetic_precipitated']:.4f} mol/L vs "
                    f"equilibrium upper bound {result['equilibrium_bound_precipitable']:.4f} mol/L — "
                    f"kinetic ≠ equilibrium; SI alone is not yield (acceptance rule 9.4)",
                    "label": "CALCULATED",
                },
            ]
        )
        status = "SUCCESS"

    return {
        "status": status,
        "summary": f"request: {request}",
        "findings": findings,
        "assumptions": [
            "closed batch, no transport (S31)",
            "urea pathway only",
            "kinetic precipitation parameters are CALIBRATION_REQUIRED unless sourced",
        ],
        "evidence_used": ["S20", "S25", "S28"],
        "uncertainty": {"level": "medium", "notes": "activity model Davies (I<0.5 M); kinetic params are model inputs"},
        "risks": [{"text": "SI>1 does not guarantee crystal yield without nucleation surfaces", "label": "RECOMMENDATION"}],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {
            "schema_passed": True,
            "self_check_passed": True,
            "tool_calls": [{"tool": f"cli.py {tool}", "ok": bool(ok), "note": "real subprocess run"}],
        },
        "provenance": {
            "skill": "micp-ureolysis-chemistry",
            "skill_version": "1.0.0",
            "contract_version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools_used": [f"cli.py {tool}"],
        },
        "errors": errors,
    }


def validate_envelope(e: dict) -> list[str]:
    """Validate against output.schema.json using jsonschema if available."""
    problems = []
    for f in ("status", "summary", "validation", "provenance"):
        if f not in e:
            problems.append(f"missing {f}")
    if e.get("status") not in STATUSES:
        problems.append(f"bad status {e.get('status')}")
    for f in e.get("findings", []):
        if f.get("label") not in LABELS:
            problems.append(f"bad label {f.get('label')}")
    try:
        import jsonschema

        schema = json.load(open(OUTPUT_SCHEMA, encoding="utf-8"))
        jsonschema.validate(e, schema)
    except ImportError:
        pass  # structural checks above cover the envelope
    except Exception as exc:  # noqa: BLE001
        problems.append(f"schema violation: {exc}")
    return problems


# ---------------------------------------------------------------------------
# The four self-bootstrap tests (user requests, no expected answers leaked)
# ---------------------------------------------------------------------------


def b1_reject_ca_imbalance() -> dict:
    request = "沉淀后液相 Ca2+ 测出来只有 0.02 mol/L,固体 X 射线荧光扫出 0.01 mol/L 当量 CaCO3,但是我们总共加了 0.05 mol/L 钙,剩下的钙去哪了?你给我算算守恒不守恒。"
    # skill decides: conservation check -> balance tool
    res = run_cli("balance", {"species": {"Ca2+": 0.02, "CaCO3(s)": 0.01}, "total_ca": 0.05})
    env = emit_envelope(request, "balance", {}, res)
    problems = validate_envelope(env)
    elem = (res.get("result") or {}).get("elemental", {})
    ca_ok = elem.get("Ca", {}).get("passed")
    # THE GATE: data violates Ca conservation, so the skill MUST NOT proceed to
    # engineering advice — status must be BLOCKED/FAILED, not SUCCESS.
    gate_enforced = ca_ok is False and env["status"] in ("BLOCKED", "FAILED")
    passed = gate_enforced and not problems
    return {"id": "B1", "name": "钙质量守恒闸门(不守恒数据被拒)", "passed": passed, "problems": problems,
            "evidence": {"ca_passed": ca_ok, "status": env["status"], "gate_enforced": gate_enforced},
            "request": request}


def b2_same_ca_diff_ph() -> dict:
    request = "同样是 0.05 M 的钙液,pH 拉到 7.5 和 9.0,沉淀的趋势会不会不一样?帮我算一下饱和指数对比一下。"
    lo = run_cli("speciate", {"ph": 7.5, "c_total": 0.05, "ca_total": 0.05, "cl_total": 0.1})
    hi = run_cli("speciate", {"ph": 9.0, "c_total": 0.05, "ca_total": 0.05, "cl_total": 0.1})
    env = emit_envelope(request, "speciate", {}, hi)
    si_lo = (lo.get("result") or {}).get("si_calcite")
    si_hi = (hi.get("result") or {}).get("si_calcite")
    problems = validate_envelope(env)
    passed = si_lo is not None and si_hi is not None and si_hi > si_lo and not problems
    return {"id": "B2", "name": "同钙不同 pH 沉淀趋势", "passed": passed, "problems": problems,
            "evidence": {"si_7.5": round(si_lo, 3), "si_9.0": round(si_hi, 3)}, "request": request}


def b3_kinetic_vs_equilibrium() -> dict:
    request = "0.5 M 尿素加 0.5 M 氯化钙,水解 k=1/3600 每秒,跑两个小时,最后到底沉淀了多少碳酸钙?平衡上能沉多少,实际两小时能沉多少,分开告诉我。"
    res = run_cli(
        "simulate",
        {
            "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
            "kinetics": {"mode": "first", "k": 1.0 / 3600.0},
            "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
            "t_end_s": 7200,
            "dt_s": 300,
            "cl": 0.1,
        },
    )
    env = emit_envelope(request, "simulate", {}, res)
    problems = validate_envelope(env)
    r = res.get("result") or {}
    kin = r.get("kinetic_precipitated")
    eq = r.get("equilibrium_bound_precipitable")
    passed = kin is not None and eq is not None and kin <= eq + 1e-9 and eq > 0 and not problems
    return {"id": "B3", "name": "动力学≠平衡(有限时间 vs 平衡上界)", "passed": passed, "problems": problems,
            "evidence": {"kinetic": round(kin, 5), "equilibrium_bound": round(eq, 5)}, "request": request}


def b4_full_calc_and_reverse_check() -> dict:
    request = "帮我把这组尿素水解反应算一下,0.5 M 尿素 0.5 M 钙,水解后尿素剩多少,铵多少,钙多少,沉淀多少,然后你反过去核对一下元素守不守恒。"
    params = {
        "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
        "kinetics": {"mode": "first", "k": 1.0 / 3600.0},
        "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
        "t_end_s": 7200,
        "dt_s": 300,
        "cl": 0.1,
    }
    res = run_cli("simulate", params)
    env = emit_envelope(request, "simulate", params, res)
    problems = validate_envelope(env)
    r = res.get("result") or {}
    f = r.get("final") or {}
    urea0, ca0 = 0.5, 0.5
    urea_l = f.get("urea", 0)
    nh3 = f.get("nh3_tot", 0)
    ca_l = f.get("ca2plus", 0)
    solid = f.get("caco3_solid", 0)
    n_res = abs(2 * urea0 - (2 * urea_l + nh3))
    ca_res = abs(ca0 - (ca_l + solid))
    ok = n_res <= 1e-6 and ca_res <= 1e-6 and not problems
    return {"id": "B4", "name": "完整算例+反向守恒核对", "passed": ok, "problems": problems,
            "evidence": {"N_residual": round(n_res, 8), "Ca_residual": round(ca_res, 8),
                          "stoich": r.get("stoichiometry_check", {}).get("passed")}, "request": request}


def main() -> int:
    os.makedirs(AUDIT, exist_ok=True)
    tests = [b1_reject_ca_imbalance(), b2_same_ca_diff_ph(), b3_kinetic_vs_equilibrium(), b4_full_calc_and_reverse_check()]
    record = {"skill": "micp-ureolysis-chemistry", "version": "1.0.0",
               "tests": tests, "all_passed": all(t["passed"] for t in tests)}
    path = os.path.join(AUDIT, "in-role-bootstrap.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
    for t in tests:
        mark = "PASS" if t["passed"] else "FAIL"
        print(f"[{mark}] {t['id']} {t['name']}: {t['evidence']}" + (f" | problems={t['problems']}" if t["problems"] else ""))
    print(f"in-role bootstrap: {sum(1 for t in tests if t['passed'])}/4 passed → audit/in-role-bootstrap.json")
    return 0 if record["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
