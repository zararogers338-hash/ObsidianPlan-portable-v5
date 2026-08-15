#!/usr/bin/env python3
"""Tests for the mini YAML subset parser used by the eval runner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.mini_yaml import loads, MiniYamlError


class TestMiniYaml(unittest.TestCase):
    def test_scalars(self):
        doc = loads("""
        a: 1
        b: 2.5
        c: true
        d: null
        e: hello
        f: "quoted"
        g: 'single'
        """)
        self.assertEqual(doc["a"], 1)
        self.assertEqual(doc["b"], 2.5)
        self.assertTrue(doc["c"])
        self.assertIsNone(doc["d"])
        self.assertEqual(doc["e"], "hello")
        self.assertEqual(doc["f"], "quoted")
        self.assertEqual(doc["g"], "single")

    def test_flow_map_list(self):
        doc = loads("""
        cases:
          - { id: eval-01, name: "x" }
          - { id: eval-02 }
        """)
        self.assertEqual(doc["cases"][0]["id"], "eval-01")
        self.assertEqual(doc["cases"][1]["id"], "eval-02")

    def test_nested_list_of_maps(self):
        doc = loads("""
        cases:
          - id: a
            expected:
              status: SUCCESS
              gap_fields: [a, b]
            score: 2
          - id: b
            expected:
              status: BLOCKED
        """)
        self.assertEqual(doc["cases"][0]["expected"]["status"], "SUCCESS")
        self.assertEqual(doc["cases"][0]["expected"]["gap_fields"], ["a", "b"])
        self.assertEqual(doc["cases"][0]["score"], 2)
        self.assertEqual(doc["cases"][1]["id"], "b")

    def test_comments_and_blank(self):
        doc = loads("""
        # a comment
        key: value   # trailing comment
        """)
        self.assertEqual(doc, {"key": "value"})

    def test_cases_yaml_parses(self):
        from tools.mini_yaml import loads as load
        path = ROOT / "evals" / "cases.yaml"
        doc = load(path.read_text(encoding="utf-8"))
        self.assertIn("cases", doc)
        self.assertGreaterEqual(len(doc["cases"]), 8)

    def test_tab_rejected(self):
        with self.assertRaises(MiniYamlError):
            loads("\tkey: value")

    def test_unbalanced_flow_rejected(self):
        with self.assertRaises(MiniYamlError):
            loads("x: { a: 1 ")


if __name__ == "__main__":
    unittest.main()
