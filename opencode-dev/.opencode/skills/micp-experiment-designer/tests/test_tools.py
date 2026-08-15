#!/usr/bin/env python3
"""Unit tests for the micp-experiment-designer toolset.

Covers the deterministic numerical core and the envelope protocol. Offline.
Run:  python -m unittest discover -s tests -p "test_*.py" -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS.parent))  # repo root for `tools` package

from tools import doe_power, quantity_calc, randomizer, sop_check, preregister, unit_validate


class TestDoePower(unittest.TestCase):
    def test_two_group_means_n(self):
        r = doe_power.main({"design": {"kind": "two_group_means", "delta": 1.5,
                                       "sigma": 2.0, "alpha": 0.05, "two_sided": True}})
        self.assertTrue(r["ok"] if isinstance(r, dict) and "ok" in r else True)
        # doe_power.main returns a result dict directly
        self.assertGreaterEqual(r["n_per_group"], 1)
        self.assertAlmostEqual(r["power_at_n"], 0.80, delta=0.05)
        self.assertEqual(r["kind"], "two_group_means")

    def test_budget_mode_reports_tradeoffs(self):
        r = doe_power.main({"design": {"kind": "two_group_means", "delta": 1.5,
                                       "sigma": 2.0}, "sample_budget": 12})
        self.assertEqual(r["n_per_group"], 12)
        self.assertGreater(len(r["tradeoffs"]), 0)
        self.assertLess(r["power_at_n"], 0.80)

    def test_delta_zero_rejected(self):
        with self.assertRaises(Exception):
            doe_power.main({"design": {"kind": "two_group_means", "delta": 0,
                                       "sigma": 2.0}})

    def test_two_prop(self):
        r = doe_power.main({"design": {"kind": "two_group_proportions",
                                       "p1": 0.2, "p2": 0.5}})
        self.assertGreaterEqual(r["n_per_group"], 1)


class TestRandomizer(unittest.TestCase):
    def test_complete_reproducible(self):
        payload = {"groups": ["A", "B"],
                   "units": [{"id": f"u{i}"} for i in range(1, 7)],
                   "method": "complete", "seed": 42}
        r1 = randomizer.main(payload)
        r2 = randomizer.main(payload)
        self.assertEqual(r1["allocation"], r2["allocation"])
        self.assertEqual(r1["checksum"], r2["checksum"])
        # each unit assigned to A or B, exactly 3 each
        groups = [x["group"] for x in r1["allocation"]]
        self.assertEqual(groups.count("A"), 3)
        self.assertEqual(groups.count("B"), 3)

    def test_blocked_requires_divisible(self):
        payload = {"groups": ["A", "B", "C"],
                   "units": [{"id": "u1", "block": "b1"}, {"id": "u2", "block": "b1"},
                             {"id": "u3", "block": "b1"}, {"id": "u4", "block": "b1"},
                             {"id": "u5", "block": "b1"}],
                   "method": "blocked", "seed": 1}
        with self.assertRaises(Exception):
            randomizer.main(payload)


class TestQuantityCalc(unittest.TestCase):
    def test_urea_mass(self):
        r = quantity_calc.main({
            "reagents": [{"name": "urea", "concentration": 1.0,
                          "concentration_unit": "mol/L", "volume": 0.5,
                          "volume_unit": "L"}]})
        mass = r["calculations"][0]["mass_g"]
        # 0.5 L * 1 mol/L = 0.5 mol; 0.5 * 60.06 = 30.03 g
        self.assertAlmostEqual(mass, 30.03, places=2)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(Exception):
            quantity_calc.main({
                "reagents": [{"name": "urea", "concentration": 1.0,
                              "concentration_unit": "foobar/L", "volume": 0.5,
                              "volume_unit": "L"}]})

    def test_dilution(self):
        r = quantity_calc.main({
            "dilution": {"c1_value": 2.0, "c1_unit": "M", "v1_value": 0.1,
                         "v1_unit": "L", "c2_value": 0.5, "c2_unit": "M"}})
        calc = r["calculations"][0]
        self.assertEqual(calc["missing"], "v2")
        # 2*0.1/0.5 = 0.4 L == 4e-4 m3 (result is in SI units)
        self.assertAlmostEqual(calc["result_si"], 4e-4, places=9)
        self.assertEqual(calc["result_si_unit"], "m3")


class TestSopCheck(unittest.TestCase):
    def test_missing_negative_control_blocks(self):
        r = sop_check.main({"design": {"objective": "x", "pathway": "urea",
                                       "replicates": 3,
                                       "endpoints": [{"name": "strength", "unit": "MPa"}]}})
        self.assertFalse(r["pass"])
        self.assertIn("negative_control", r["blocking_issues"])

    def test_complete_design_passes(self):
        design = {"objective": "x", "pathway": "urea", "replicates": 3,
                  "endpoints": [{"name": "strength", "unit": "MPa"}],
                  "negative_control": True, "positive_control": True,
                  "data_exclusion": "drop contaminated",
                  "stop_condition": "stop if strength < threshold",
                  "safety": ["biosafety cabinet"], "ammonium_accounting": True}
        r = sop_check.main({"design": design})
        self.assertTrue(r["pass"])
        self.assertEqual(r["mode"], "generate")


class TestPreregister(unittest.TestCase):
    def test_missing_sample_size_advisory(self):
        r = preregister.main({"design": {"objective": "x",
                                         "primary_hypothesis": "h",
                                         "endpoints": [{"name": "s", "unit": "MPa"}],
                                         "groups": ["A", "B"]}})
        self.assertEqual(r["preregistration"]["sample_size"], "TBD")
        self.assertIsNotNone(r["blocking_advisory"])

    def test_with_sample_size(self):
        r = preregister.main({"design": {"objective": "x",
                                         "primary_hypothesis": "h",
                                         "endpoints": [{"name": "s", "unit": "MPa"}],
                                         "groups": ["A", "B"]},
                              "sample_size": 10})
        self.assertEqual(r["preregistration"]["sample_size"], 10)
        self.assertIsNone(r["blocking_advisory"])


class TestUnitValidate(unittest.TestCase):
    def test_conversion(self):
        self.assertAlmostEqual(unit_validate.convert(1.0, "mol/L", "mmol/L"), 1000.0)

    def test_incompatible(self):
        with self.assertRaises(Exception):
            unit_validate.convert(1.0, "MPa", "g")


class TestEnvelopeCLI(unittest.TestCase):
    """Integration: the CLI entrypoint behaves as documented (exit codes)."""

    def _run(self, payload: dict):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.cli"],
            input=json.dumps(payload),
            capture_output=True, text=True,
            cwd=str(TOOLS.parent),
            timeout=60,
        )
        return proc

    def test_unknown_tool_exit_2(self):
        proc = self._run({"tool": "nope", "payload": {}})
        self.assertEqual(proc.returncode, 2)
        out = json.loads(proc.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("error", out)

    def test_doe_power_exit_0(self):
        proc = self._run({"tool": "doe_power",
                          "payload": {"design": {"kind": "two_group_means",
                                                 "delta": 1.5, "sigma": 2.0}}})
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertIn("n_per_group", out["result"])

    def test_bad_json_exit_2(self):
        proc = subprocess.run([sys.executable, "-m", "tools.cli"],
                              input="{not json",
                              capture_output=True, text=True,
                              cwd=str(TOOLS.parent), timeout=60)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
