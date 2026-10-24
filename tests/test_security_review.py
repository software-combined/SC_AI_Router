"""Security is required by setup and represented in both client packages."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/development/scg-review'
spec = importlib.util.spec_from_file_location('security_review_setup', PLUGIN / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SecurityReviewTests(unittest.TestCase):
    def test_setup_rejects_three_lane_configuration_before_running_scanner(self):
        self.assertEqual(setup.LANES, ['correctness', 'quality', 'adversarial', 'security'])
        with self.assertRaisesRegex(ValueError, 'security'):
            setup.verify_config({'required_lanes': ['correctness', 'quality', 'adversarial']})

    def test_both_clients_ship_the_same_model_agnostic_security_contract(self):
        skill = PLUGIN / 'skills/security-review/SKILL.md'
        self.assertTrue(skill.is_file())
        agent = (PLUGIN / 'agents/review-security.md').read_text()
        frontmatter = agent.split('---')[1]
        self.assertNotIn('model:', frontmatter)
        self.assertNotIn('effort:', frontmatter)
        self.assertIn('security-review', agent)
        codex = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(codex['skills'], './skills/')
        claude = json.loads((PLUGIN / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(claude['version'], codex['version'])

    def test_release_bundle_includes_security_agent_skill_and_licence(self):
        spec = importlib.util.spec_from_file_location('security_review_release', ROOT / 'packaging/release.py')
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        files = release.plugin_files(ROOT)
        for name in ('agents/review-security.md', 'skills/security-review/SKILL.md',
                     'support/cloudflare-LICENSE.txt'):
            self.assertIn('plugins/development/scg-review/' + name, files)


if __name__ == '__main__':
    unittest.main()
