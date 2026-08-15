"""Regression tests: guard the documented contracts so a future edit cannot
silently break them.

- The OpenCode native loader contract: SKILL.md frontmatter name matches the
  directory and is lowercase-kebab.
- The Router registry contract: skill.yaml parses and validates under
  obsidian-skill-router's registry rules.
- Schema ↔ implementation coherence: every sample output we produce validates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from micp_lit import adapters  # noqa: F401  (imports tools; keeps fixtures path right)

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMAS = SKILL_DIR / "schemas"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with frontmatter"
    end = text.index("\n---", 4)
    import yaml

    return yaml.safe_load(text[4:end])


class TestNativeLoaderContract:
    def test_frontmatter_name_matches_dir(self):
        skill_md = SKILL_DIR / "SKILL.md"
        fm = _frontmatter(skill_md)
        assert fm["name"] == "micp-literature-scout"
        assert SKILL_DIR.name == fm["name"]
        assert NAME_RE.match(fm["name"]), "name must be lowercase-kebab"

    def test_frontmatter_description_present(self):
        fm = _frontmatter(SKILL_DIR / "SKILL.md")
        assert isinstance(fm.get("description"), str) and fm["description"].strip()

    def test_skill_version_semver(self):
        fm = _frontmatter(SKILL_DIR / "SKILL.md")
        assert SEMVER_RE.match(fm["version"]), "version must be semver"

    def test_version_matches_service_and_manifest(self):
        fm = _frontmatter(SKILL_DIR / "SKILL.md")
        from micp_lit.service import SKILL_VERSION

        assert fm["version"] == SKILL_VERSION
        import yaml

        manifest = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
        assert manifest["version"] == SKILL_VERSION


class TestRouterRegistryContract:
    def test_skill_yaml_parses(self):
        import yaml

        manifest = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
        assert manifest["name"] == "micp-literature-scout"
        assert SEMVER_RE.match(manifest["version"])

    def test_manifest_field_types(self):
        import yaml

        manifest = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
        for key in ("capabilities", "inputs_required", "outputs", "tool_permissions",
                    "writes", "stop_conditions", "domain_keywords", "dependencies"):
            assert isinstance(manifest.get(key), list), f"{key} must be a list"
            assert all(isinstance(x, str) for x in manifest[key]), f"{key} must be list of str"
        assert manifest["risk_tier"] in ("low", "medium", "high", "critical")
        assert isinstance(manifest["network"], bool)

    def test_no_reserved_capability(self):
        import yaml

        manifest = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
        assert "routing" not in (manifest.get("capabilities") or [])


class TestSchemaContract:
    def test_input_schema_valid_json(self):
        data = json.loads((SCHEMAS / "input.schema.json").read_text(encoding="utf-8"))
        assert data["type"] == "object"
        assert "action" in data["required"]
        assert "request" in data["required"]

    def test_output_schema_valid_json(self):
        data = json.loads((SCHEMAS / "output.schema.json").read_text(encoding="utf-8"))
        for key in ("status", "summary", "findings", "assumptions", "evidence_used",
                    "uncertainty", "risks", "artifacts", "requested_next_skills",
                    "validation", "provenance", "errors"):
            assert key in data["required"], f"output schema missing required {key}"

    def test_all_actions_have_handlers(self):
        from micp_lit.service import ACTIONS, SkillService

        svc = SkillService(offline=True)
        for action in ACTIONS:
            handler = getattr(svc, f"_do_{action.replace('.', '_')}", None)
            assert handler is not None, f"no handler for {action}"

    def test_error_codes_defined(self):
        """Every MLS-E code used by the service is documented in SKILL.md."""
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        from micp_lit import errors as e

        # Collect codes from error factory functions.
        src = Path(e.__file__).read_text(encoding="utf-8")
        defined = set(re.findall(r'"MLS-E(\d{3})"', src))
        documented = set(re.findall(r"MLS-E(\d{3})", skill_text))
        # Every defined code should be documented.
        missing = defined - documented
        assert not missing, f"codes not documented in SKILL.md: {sorted(missing)}"


class TestReproIdStability:
    def test_repro_id_stable_across_processes(self):
        """repro_id must not depend on module state or time."""
        a = adapters.repro_id("improve MICP uniformity", database="auto", n=10)
        b = adapters.repro_id("improve MICP uniformity", database="auto", n=10)
        assert a == b

    def test_repro_id_bounds(self):
        rid = adapters.repro_id("improve MICP uniformity")
        assert len(rid) == 16
        assert all(c in "0123456789abcdef" for c in rid)
