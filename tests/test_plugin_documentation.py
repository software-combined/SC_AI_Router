"""SCG documentation plugin stays installed, dual-runtime and well-formed."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/scg-documentation"
SKILL = PLUGIN / "skills/documentation"


class DocumentationPluginTest(unittest.TestCase):
    def test_marketplace_entry_and_codex_manifest_resolve_inside_package(self):
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertIn("scg-documentation", entries)
        self.assertEqual((ROOT / entries["scg-documentation"]["source"]["path"]).resolve(), PLUGIN)
        manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "scg-documentation")
        self.assertEqual(manifest["repository"], "https://github.com/software-combined/SC_AI_Router_Public")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?$")

    def test_claude_manifest_matches_codex_name_and_version(self):
        codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        claude = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(claude["version"], codex["version"])

    def test_skill_front_matter_and_runbook_links_resolve(self):
        skill = (SKILL / "SKILL.md").read_text()
        head = skill.split("---")[1]
        self.assertIn("name: documentation", head)
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
        review = ROOT / "plugins/scg-review/references/updates.md"
        self.assertEqual((SKILL / "references/updates.md").read_bytes(), review.read_bytes())

    def test_skill_leads_with_reader_level_clarity(self):
        skill = (SKILL / "SKILL.md").read_text()
        self.assertIn("## Writing For Readers At Any Technical Level", skill)
        for requirement in (
            "Expand jargon on first use",
            "Never assume history",
            "Lead with the common case",
            "One idea per sentence",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, skill)

    def test_skill_is_one_document_without_heading_level_skips(self):
        in_fence, previous, h1 = False, 0, 0
        for line in (SKILL / "SKILL.md").read_text().splitlines():
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not line.startswith("#"):
                continue
            level = len(line) - len(line.lstrip("#"))
            with self.subTest(heading=line):
                self.assertLessEqual(level, previous + 1)
            previous = level
            h1 += level == 1
        self.assertEqual(h1, 1)


if __name__ == "__main__":
    unittest.main()
