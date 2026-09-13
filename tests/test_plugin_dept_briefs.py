"""Department delegation briefs stay present, well-formed and linked."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/scg-subagents/skills"
BRIEFS = ("sales-subagent", "csm-subagent", "support-subagent",
          "finance-subagent", "operations-subagent")


class DeptBriefsTest(unittest.TestCase):
    def test_every_brief_exists_with_matching_front_matter(self):
        for name in BRIEFS:
            with self.subTest(skill=name):
                skill = (SKILLS / name / "SKILL.md").read_text()
                head = skill.split("---")[1]
                self.assertIn(f"name: {name}", head)
                self.assertIn("description:", head)

    def test_every_brief_carries_the_required_sections(self):
        for name in BRIEFS:
            with self.subTest(skill=name):
                skill = (SKILLS / name / "SKILL.md").read_text()
                for section in ("## Role", "## Model", "## Inputs",
                                "## Authority", "## Acceptance"):
                    self.assertIn(section, skill)
                self.assertIn("optimal-subagents", skill)
                self.assertIn("updates.md", skill)

    def test_brief_links_resolve_inside_the_plugin(self):
        plugin = ROOT / "plugins/scg-subagents"
        for name in BRIEFS:
            markdown = SKILLS / name / "SKILL.md"
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text()):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(plugin), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_entrypoint_points_at_every_brief(self):
        entry = (SKILLS / "optimal-subagents/SKILL.md").read_text()
        for name in BRIEFS:
            self.assertIn(f"../{name}/SKILL.md", entry)


if __name__ == "__main__":
    unittest.main()
