"""SCG finance plugin stays installed, dual-runtime and well-formed."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT.parent / "plugins/finance/scg-finance"
SKILL = PLUGIN / "skills/finance-analyst"


class FinancePluginTest(unittest.TestCase):
    def test_marketplace_entry_and_codex_manifest_resolve_inside_package(self):
        marketplace = json.loads((ROOT.parent / ".agents/plugins/marketplace.json").read_text())
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertIn("scg-finance", entries)
        self.assertEqual((ROOT.parent / entries["scg-finance"]["source"]["path"]).resolve(), PLUGIN)
        manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "scg-finance")
        self.assertEqual(manifest["repository"], "https://github.com/software-combined/SC_AI")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?$")

    def test_claude_manifest_matches_codex_name_and_version(self):
        codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        claude = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(claude["version"], codex["version"])

    def test_skill_front_matter_and_runbook_links_resolve(self):
        skill = (SKILL / "SKILL.md").read_text()
        head = skill.split("---")[1]
        self.assertIn("name: finance-analyst", head)
        self.assertIn("description:", head)
        self.assertIn("updates.md", skill)
        for markdown in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text()):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(PLUGIN), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_updates_guide_is_the_shared_copy(self):
        review = ROOT.parent / "plugins/development/scg-review/references/updates.md"
        self.assertEqual((SKILL / "references/updates.md").read_bytes(), review.read_bytes())


if __name__ == "__main__":
    unittest.main()
