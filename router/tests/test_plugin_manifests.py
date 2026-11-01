"""Plan 112 step 1: plugin manifests stay valid, versioned, and consistent.

Proves: both manifests parse, carry the same name and the packaging/VERSION
semver, the shared skill exists with the required front-matter, and the
skill's installer commands resolve to files in this repository.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PluginManifestTests(unittest.TestCase):
    def _manifest(self, name):
        path = ROOT.parent / name / 'plugin.json'
        return json.loads(path.read_text()), path

    def test_manifests_share_name_and_packaging_version(self):
        version = (ROOT / 'packaging' / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        for name in ('.codex-plugin', '.claude-plugin'):
            manifest, path = self._manifest(name)
            with self.subTest(plugin=name):
                self.assertEqual(manifest['name'], 'scg-openrouter', path)
                self.assertEqual(manifest['version'], version, path)

    def test_manifests_describe_setup_without_auto_mutation(self):
        for name in ('.codex-plugin', '.claude-plugin'):
            manifest, path = self._manifest(name)
            with self.subTest(plugin=name):
                text = manifest.get('description', '')
                self.assertIn('install', text.lower(), path)
                self.assertNotIn('automatically', text.lower(), path)

    def test_shared_skill_exists_with_required_front_matter(self):
        skill = ROOT.parent / 'skills' / 'manage-router' / 'SKILL.md'
        self.assertTrue(skill.is_file(), skill)
        head = skill.read_text().split('---')[1]
        self.assertIn('name: manage-router', head)
        self.assertIn('description:', head)

    def test_skill_installer_commands_resolve_in_repo(self):
        skill = (ROOT.parent / 'skills' / 'manage-router' / 'SKILL.md').read_text()
        commands = set(re.findall(r'(?<!router/)packaging/\S+\.py', skill))
        self.assertTrue(commands, 'skill names no installer entry points')
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue((ROOT / command).is_file(), command)

    def test_skill_forbids_secret_bearing_output(self):
        skill = (ROOT.parent / 'skills' / 'manage-router' / 'SKILL.md').read_text().lower()
        for phrase in ('never print tokens', 'never ask for the key'):
            self.assertIn(phrase, skill)


if __name__ == '__main__':
    unittest.main()
