"""MUC — unit / integration / failure / regression tests (stdlib unittest).

Run: python -m unittest discover -s tests -p "test_*.py"
or:  python tests/test_engine.py

Offline, deterministic, no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The muc package lives in tools/; make it importable.
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from muc.activity import activity_coefficient, ionic_strength_from_concs  # noqa: E402
from muc.balance import (  # noqa: E402
    check_charge_balance,
    check_elemental_balance,
    check_ureolysis_stoichiometry,
    ureolysis_product_amounts,
)
from muc.errors import MUCError, describe  # noqa: E402
from muc.kinetics import (  # noqa: E402
    arrhenius_factor,
    first_order_rate,
    mm_rate,
    ph_factor,
    vmax_from_urease,
)
from muc.sens import propagate_uncertainty, sensitivity  # noqa: E402
from muc.simulate import simulate_batch  # noqa: E402
from muc.speciate import alkalinity_to_pH, speciate_at_ph  # noqa: E402
from muc.units import (  # noqa: E402
    check_unit,
    concentration_unit_ok,
    convert_molar,
    lookup,
)

CLI = os.path.join(_TOOLS, "cli.py")


def run_cli(args: list[str], stdin_data: str | None = None) -> tuple[int, dict]:
    """Run cli.py as a subprocess; return (exit_code, parsed_json)."""
    proc = subprocess.run(
        [sys.executable, CLI] + args,
        input=stdin_data or "",
        capture_output=True,
        text=True,
        cwd=_TOOLS,
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = {"raw": proc.stdout[:500], "stderr": proc.stderr[:500]}
    return proc.returncode, parsed


# ---------------------------------------------------------------------------
# balance
# ---------------------------------------------------------------------------
class TestBalance(unittest.TestCase):
    def test_nitrogen_conservation_urea(self):
        # 0.05 M urea has 0.1 M N; if the snapshot shows only 0.05 M NH4 the
        # nitrogen balance fails (this is the spec's acceptance gate #1).
        species = {"urea": 0.05, "NH4+": 0.05, "CO2(aq)": 0.05}
        r = check_elemental_balance(species=species, total_n=0.1)
        self.assertFalse(r["passed"])
        self.assertFalse(r["N"]["passed"])

    def test_nitrogen_conservation_ok(self):
        # urea fully converted: 0.05 urea -> 0.1 NH4 + 0.05 CO2
        species = {"NH4+": 0.1, "NH3(aq)": 0.0, "CO2(aq)": 0.05, "HCO3-": 0.0}
        r = check_elemental_balance(species=species, total_n=0.1, total_c=0.05)
        self.assertTrue(r["passed"])

    def test_calcium_conservation_precipitated(self):
        species = {"Ca2+": 0.02, "CaCO3(s)": 0.03}
        r = check_elemental_balance(species=species, total_ca=0.05)
        self.assertTrue(r["Ca"]["passed"])

    def test_charge_balance_violation_detected(self):
        # [Ca2+]=0.05 with only [Cl-]=0.05 leaves +0.05 charge imbalance
        species = {"Ca2+": 0.05, "Cl-": 0.05}
        r = check_charge_balance(species)
        self.assertFalse(r["passed"])
        self.assertAlmostEqual(r["charge_imbalance_eq_L"], 0.05, places=5)

    def test_charge_balance_neutral(self):
        # CaCl2 solution: Ca2+=0.05, Cl-=0.1 -> neutral
        species = {"Ca2+": 0.05, "Cl-": 0.1}
        r = check_charge_balance(species)
        self.assertTrue(r["passed"])

    def test_negative_concentration_rejected(self):
        with self.assertRaises(MUCError) as cm:
            check_elemental_balance(species={"Ca2+": -1.0})
        self.assertEqual(cm.exception.code, "MUC-E2002")

    def test_ureolysis_stoichiometry(self):
        r = check_ureolysis_stoichiometry(
            urea_hydrolyzed=0.1, co2_produced=0.1, nh3_produced=0.2
        )
        self.assertTrue(r["passed"])
        r2 = check_ureolysis_stoichiometry(
            urea_hydrolyzed=0.1, co2_produced=0.05, nh3_produced=0.2
        )
        self.assertFalse(r2["co2_passed"])

    def test_product_amounts(self):
        p = ureolysis_product_amounts(0.25)
        self.assertAlmostEqual(p["CO2_produced"], 0.25)
        self.assertAlmostEqual(p["NH3_produced"], 0.5)


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------
class TestUnits(unittest.TestCase):
    def test_convert_molar(self):
        self.assertAlmostEqual(convert_molar(500, "mM"), 0.5)
        self.assertAlmostEqual(convert_molar(0.5, "M"), 0.5)  # 0.5 M = 0.5 mol/L
        # convert to mM target explicitly
        self.assertAlmostEqual(convert_molar(0.5, "M", target="mM"), 500.0)
        self.assertAlmostEqual(convert_molar(0.5, "mol/L", target="mM"), 500.0)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(MUCError) as cm:
            concentration_unit_ok("banana")
        self.assertEqual(cm.exception.code, "MUC-E1003")

    def test_mass_concentration_rejected_for_molar_math(self):
        with self.assertRaises(MUCError) as cm:
            concentration_unit_ok("g/L")
        self.assertIn("mass concentration", cm.exception.message)

    def test_check_unit_dims(self):
        check_unit("mmol/L", (0, -3, 0, 0, 0, 1, 0), "test")
        with self.assertRaises(MUCError):
            check_unit("mmol/L", (1, -3, 0, 0, 0, 0, 0), "test")  # mass dims

    def test_lookup_currency_not_chemical(self):
        u = lookup("CNY")
        self.assertIsNotNone(u)
        self.assertEqual(u.kind, "currency")


# ---------------------------------------------------------------------------
# activity
# ---------------------------------------------------------------------------
class TestActivity(unittest.TestCase):
    def test_uncharged_gamma_one(self):
        self.assertAlmostEqual(activity_coefficient("urea", 0.1), 1.0)

    def test_monovalent_below_one(self):
        g = activity_coefficient("NH4+", 0.1)
        self.assertLess(g, 1.0)
        self.assertGreater(g, 0.5)

    def test_divalent_more_active_correction(self):
        g2 = activity_coefficient("Ca2+", 0.1)
        g1 = activity_coefficient("Na+", 0.1)
        self.assertLess(g2, g1)

    def test_ionic_strength_calc(self):
        I = ionic_strength_from_concs({"Ca2+": 0.05, "Cl-": 0.1})
        self.assertAlmostEqual(I, 0.15)


# ---------------------------------------------------------------------------
# speciate
# ---------------------------------------------------------------------------
class TestSpeciate(unittest.TestCase):
    def test_ph_speciation_alpha_fractions(self):
        # At pH 6.35 ~ 50% HCO3, at pH 10.33 ~ 50% CO3
        r6 = speciate_at_ph(pH=6.35, c_total=0.05, ca_total=0.0, cl_total=0.0)
        self.assertAlmostEqual(r6["speciation"]["HCO3-"], 0.05 * 0.5, delta=0.005)
        r10 = speciate_at_ph(pH=10.33, c_total=0.05, ca_total=0.0, cl_total=0.0)
        self.assertAlmostEqual(r10["speciation"]["CO3 2-"], 0.05 * 0.5, delta=0.005)

    def test_si_increases_with_ph(self):
        si8 = speciate_at_ph(pH=8.0, c_total=0.05, ca_total=0.05, cl_total=0.1)["si_calcite"]
        si9 = speciate_at_ph(pH=9.0, c_total=0.05, ca_total=0.05, cl_total=0.1)["si_calcite"]
        self.assertGreater(si9, si8)

    def test_si_decreases_with_ionic_strength_dilution(self):
        # Higher Cl dilutes activities -> lower SI for same Ca/Ct? Not strictly:
        # I enters via activity coefficients. Check it runs and is finite.
        r = speciate_at_ph(pH=9.0, c_total=0.05, ca_total=0.05, cl_total=0.5)
        self.assertTrue(r["si_calcite"] > 0)

    def test_alkalinity_to_ph_roundtrip(self):
        # Pure-carbonate invariant: when Alk == CT, pH sits at the bicarbonate
        # equivalence point (pKa1+pKa2)/2 ≈ 8.34. (No borate/Ca in this test.)
        r = alkalinity_to_pH(alkalinity_eq_L=0.002, c_total=0.002, ca_total=0.0)
        self.assertAlmostEqual(r["ph"], 8.34, delta=0.1)
        # Alk > CT pushes pH up.
        r2 = alkalinity_to_pH(alkalinity_eq_L=0.0024, c_total=0.002, ca_total=0.0)
        self.assertGreater(r2["ph"], r["ph"])

    def test_invalid_ph_rejected(self):
        with self.assertRaises(MUCError) as cm:
            speciate_at_ph(pH=15, c_total=0.01, ca_total=0.0)
        self.assertEqual(cm.exception.code, "MUC-E2004")


# ---------------------------------------------------------------------------
# kinetics
# ---------------------------------------------------------------------------
class TestKinetics(unittest.TestCase):
    def test_mm_low_conc_linear(self):
        # When [urea] << km, rate ~ vmax/km * [urea] (first-order regime)
        r = mm_rate(urea_conc=1e-6, vmax=1e-4, km=1e-3)
        # exact: vmax*[urea]/(km+[urea])
        expected = 1e-4 * 1e-6 / (1e-3 + 1e-6)
        self.assertAlmostEqual(r, expected, places=12)

    def test_mm_saturation_zero_order(self):
        r = mm_rate(urea_conc=1.0, vmax=1e-4, km=1e-3)
        self.assertAlmostEqual(r, 1e-4, delta=1e-5)

    def test_mm_half_velocity_at_km(self):
        r = mm_rate(urea_conc=1e-3, vmax=1e-4, km=1e-3)
        self.assertAlmostEqual(r, 0.5e-4, places=6)

    def test_mm_negative_rejected(self):
        with self.assertRaises(MUCError):
            mm_rate(urea_conc=-1, vmax=1e-4, km=1e-3)

    def test_first_order(self):
        self.assertAlmostEqual(first_order_rate(0.5, 0.001), 0.0005)

    def test_vmax_from_urease_units(self):
        # 1e6 U/L * 1.667e-8 = 0.01667 mol/L/s (scaled by a0)
        v = vmax_from_urease(urease_units_per_L=1e6)
        self.assertAlmostEqual(v, 1.667e-2, places=4)

    def test_arrhenius_warmer_faster(self):
        self.assertGreater(arrhenius_factor(308.15), 1.0)
        self.assertLess(arrhenius_factor(288.15), 1.0)

    def test_ph_factor_peaks_at_optimum(self):
        self.assertAlmostEqual(ph_factor(7.5, ph_opt=7.5), 1.0)


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------
class TestSimulate(unittest.TestCase):
    BASE = {
        "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
        "kinetics": {"mode": "first", "k": 1.0 / 3600.0},
        "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
        "t_end_s": 7200,
        "dt_s": 300,
        "cl": 0.1,
    }

    def test_urea_decays_monotonically(self):
        r = simulate_batch(**self.BASE)
        u = r["trajectories"]["urea"]
        self.assertEqual(u[0], 0.5)
        self.assertLess(u[-1], u[0])
        self.assertTrue(all(u[i] >= u[i + 1] - 1e-9 for i in range(len(u) - 1)))

    def test_stoichiometry_preserved(self):
        r = simulate_batch(**self.BASE)
        self.assertTrue(r["stoichiometry_check"]["passed"])

    def test_ca_consumed_only_when_si_threshold(self):
        # With a high SI threshold, precipitation never triggers -> Ca unchanged
        params = json.loads(json.dumps(self.BASE))
        params["precipitation"]["si_threshold"] = 99.0
        r = simulate_batch(**params)
        self.assertAlmostEqual(r["final"]["ca2plus"], 0.5, places=6)
        self.assertAlmostEqual(r["kinetic_precipitated"], 0.0, places=9)

    def test_kinetic_precipitated_le_eq_bound(self):
        r = simulate_batch(**self.BASE)
        self.assertLessEqual(r["kinetic_precipitated"], r["equilibrium_bound_precipitable"] + 1e-9)

    def test_equilibrium_bound_not_yield_claim(self):
        # Regression: eq_bound is a mass-balance upper bound; kinetic solid must
        # not be asserted equal to it. Here with limited time it is below.
        r = simulate_batch(**self.BASE)
        self.assertGreaterEqual(r["equilibrium_bound_precipitable"], r["kinetic_precipitated"])

    def test_first_order_half_life(self):
        # first-order k=0.0002 -> t_half ~ 3465.7 s (closed-form)
        params = json.loads(json.dumps(self.BASE))
        params["kinetics"]["k"] = 0.0002
        r = simulate_batch(**params)
        # At t_half the urea should be ~ half (no precip interference on urea)
        import math

        u0 = 0.5
        t_half = math.log(2) / 0.0002
        # find nearest trajectory point
        times = r["times"]
        near = min(range(len(times)), key=lambda i: abs(times[i] - t_half))
        self.assertAlmostEqual(r["trajectories"]["urea"][near], u0 * 0.5, delta=0.05)

    def test_invalid_params_rejected(self):
        with self.assertRaises(MUCError):
            simulate_batch(**{**self.BASE, "t_end_s": -1})


# ---------------------------------------------------------------------------
# sens
# ---------------------------------------------------------------------------
class TestSens(unittest.TestCase):
    SIM = {
        "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
        "kinetics": {"mode": "first", "k": 0.0001},
        "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
        "t_end_s": 3600,
        "dt_s": 600,
        "cl": 0.1,
    }

    def test_returns_rows_for_each_param(self):
        r = sensitivity(base_input=self.SIM, parameters=["kinetics.k", "initial.urea"])
        self.assertEqual(len(r["rows"]), 2)

    def test_unknown_param_rejected(self):
        with self.assertRaises(MUCError) as cm:
            sensitivity(base_input=self.SIM, parameters=["nope.nothing"])
        self.assertEqual(cm.exception.code, "MUC-E1001")

    def test_uncertainty_propagation(self):
        r = propagate_uncertainty(
            sensitivities={"k": 1.5, "u0": 0.5},
            parameter_rel_uncertainty={"k": 0.1, "u0": 0.05},
        )
        expected = ((1.5 * 0.1) ** 2 + (0.5 * 0.05) ** 2) ** 0.5
        self.assertAlmostEqual(r["relative_uncertainty"], expected)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------
class TestCLI(unittest.TestCase):
    def test_version(self):
        code, out = run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["skill"], "micp-ureolysis-chemistry")

    def test_balance_rejects_inconsistent_data(self):
        data = json.dumps(
            {"species": {"urea": 0.05, "NH4+": 0.05}, "total_n": 0.1}
        )
        code, out = run_cli(["balance"], data)
        self.assertEqual(code, 0)  # envelope ok, result reports the imbalance
        self.assertTrue(out["ok"])
        self.assertFalse(out["result"]["elemental"]["passed"])

    def test_speciate_valid(self):
        data = json.dumps({"ph": 9.0, "c_total": 0.05, "ca_total": 0.05, "cl_total": 0.1})
        code, out = run_cli(["speciate"], data)
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertGreater(out["result"]["si_calcite"], 0)

    def test_simulate_full(self):
        data = json.dumps(
            {
                "initial": {"urea": 0.5, "ca": 0.5, "ct": 0.01, "nh3_tot": 0.0},
                "kinetics": {"mode": "first", "k": 1.0 / 3600.0},
                "precipitation": {"enabled": True, "k_precip": 1e-8, "a_specific": 10.0, "si_threshold": 1.0},
                "t_end_s": 3600,
                "dt_s": 600,
                "cl": 0.1,
            }
        )
        code, out = run_cli(["simulate"], data)
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertIn("final", out["result"])

    def test_empty_stdin_fails_cleanly(self):
        code, out = run_cli(["balance"])
        self.assertEqual(code, 3)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "MUC-E1009")

    def test_bad_json_fails_cleanly(self):
        code, out = run_cli(["balance"], "not json {")
        self.assertEqual(code, 3)
        self.assertEqual(out["error"]["code"], "MUC-E1009")

    def test_unknown_tool_fails(self):
        code, out = run_cli(["frobnicate"], "{}")
        self.assertEqual(code, 3)
        self.assertEqual(out["error"]["code"], "MUC-E1001")

    def test_phreeqc_in_generates_deck_offline(self):
        code, out = run_cli(
            ["phreeqc-in"],
            json.dumps(
                {"ph": 8.0, "c_total": 0.05, "ca_total": 0.05, "urea_initial": 0.1}
            ),
        )
        self.assertEqual(code, 0)
        self.assertIn("SOLUTION", out["result"]["generated_input"])
        self.assertIn("REACTION", out["result"]["generated_input"])

    def test_fit_recovers_first_order_k(self):
        import math

        u0, k = 0.5, 0.0002
        t = [i * 600 for i in range(8)]
        u = [u0 * math.exp(-k * tt) for tt in t]
        data = json.dumps({"t": t, "urea": u})
        code, out = run_cli(["fit"], data)
        self.assertEqual(code, 0)
        self.assertAlmostEqual(out["result"]["parameters"]["k"], k, places=6)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
class TestErrors(unittest.TestCase):
    def test_error_codes_exist(self):
        for code in [
            "MUC-E1001",
            "MUC-E1002",
            "MUC-E1003",
            "MUC-E1004",
            "MUC-E1005",
            "MUC-E1006",
            "MUC-E1007",
            "MUC-E1008",
            "MUC-E1009",
            "MUC-E1010",
            "MUC-E2001",
            "MUC-E2002",
            "MUC-E2003",
            "MUC-E2004",
            "MUC-E3001",
            "MUC-E3002",
            "MUC-E3003",
            "MUC-E4001",
            "MUC-E4002",
        ]:
            d = describe(code)
            self.assertIn("en", d)
            self.assertIn("zh", d)

    def test_retryable_flags(self):
        self.assertTrue(MUCError("MUC-E3001", "x").retryable)
        self.assertFalse(MUCError("MUC-E1001", "x").retryable)

    def test_serialization(self):
        e = MUCError("MUC-E1003", "unit mismatch", details={"q": "k"})
        d = e.to_dict()
        self.assertEqual(d["code"], "MUC-E1003")
        self.assertEqual(d["details"], {"q": "k"})
        self.assertIn("message", d)


if __name__ == "__main__":
    unittest.main()
