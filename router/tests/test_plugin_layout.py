"""Domain folders preserve plugin discovery, package boundaries and delivery."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.test_agent_skills import release, skills

ROOT = Path(__file__).resolve().parents[1]


class PluginLayoutTests(unittest.TestCase):
    def test_factory_migration_delivers_one_independent_skill_to_both_clients(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'marketplace'
            relative = 'skills/ai-agent-factory-method/SKILL.md'
            old = target / 'plugins/scg-subagents' / relative
            old.parent.mkdir(parents=True)
            old.write_text('previous bundled factory skill')
            (target / skills.MARKER).write_text('router-owned fixture')
            names = skills.write_marketplace(target, ROOT.parent / 'plugins')
            self.assertIn('scg-agent-factory', names)
            self.assertIn('scg-subagents', names)
            delivered = target / 'plugins/scg-agent-factory' / relative
            source = ROOT.parent / 'plugins/agents/scg-agent-factory' / relative
            self.assertEqual(delivered.read_bytes(), source.read_bytes())
            self.assertEqual(list((target / 'plugins').glob('*/' + relative)),
                             [delivered])
            bundled = set(release.plugin_files(ROOT))
            self.assertIn(source.relative_to(ROOT.parent).as_posix(), bundled)
            self.assertNotIn('plugins/agents/scg-subagents/' + relative, bundled)
            for manifest in ('.agents/plugins/marketplace.json',
                             '.claude-plugin/marketplace.json'):
                entries = json.loads((target / manifest).read_text())['plugins']
                self.assertEqual([p['name'] for p in entries].count('scg-agent-factory'), 1)
                entry = next(p for p in entries if p['name'] == 'scg-agent-factory')
                path = entry['source']
                if isinstance(path, dict):
                    path = path['path']
                self.assertEqual((target / path / relative).read_bytes(), source.read_bytes())

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.plugins = self.root / 'plugins'
        self.source = self.plugins / 'development/scg-example'
        for client in ('codex', 'claude'):
            self.write(f'.{client}-plugin/plugin.json',
                       json.dumps({'name': 'scg-example', 'version': '0.1.0'}))
        self.write('skills/example/SKILL.md', '# Example\n')
        self.write('scripts/setup.py', '# retained helper\n')
        self.write('scripts/updater.py', '# retired updater\n')
        self.write('scripts/scheduling.py', '# retired scheduler\n')

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_grouped_sources_keep_flat_client_paths_and_identical_skill_bytes(self):
        target = self.root / 'marketplace'
        self.assertEqual(sorted(skills.plugin_sources(self.plugins)), ['scg-example'])
        self.assertEqual(skills.write_marketplace(target, self.plugins), ['scg-example'])
        for manifest, field in (('.agents/plugins/marketplace.json', 'codex'),
                                ('.claude-plugin/marketplace.json', 'claude')):
            entry = json.loads((target / manifest).read_text())['plugins'][0]
            path = entry['source']['path'] if field == 'codex' else entry['source']
            self.assertEqual(path, './plugins/scg-example')
            self.assertEqual((target / path / 'skills/example/SKILL.md').read_bytes(),
                             (self.source / 'skills/example/SKILL.md').read_bytes())

    def test_grouped_bundle_keeps_helpers_and_withholds_retired_updaters(self):
        prefix = 'plugins/development/scg-example/'
        self.assertEqual(set(release.plugin_files(self.root)), {
            prefix + '.codex-plugin/plugin.json', prefix + '.claude-plugin/plugin.json',
            prefix + 'skills/example/SKILL.md', prefix + 'scripts/setup.py',
        })

    def test_duplicate_names_are_refused_before_a_marketplace_is_written(self):
        duplicate = self.plugins / 'finance/scg-example/.codex-plugin'
        duplicate.mkdir(parents=True)
        (duplicate / 'plugin.json').write_text('{}')
        target = self.root / 'marketplace'
        with self.assertRaisesRegex(ValueError, 'duplicate plugin name'):
            skills.write_marketplace(target, self.plugins)
        self.assertFalse(target.exists())

    def test_domain_navigation_covers_every_skill_and_ships_with_the_bundle(self):
        bundled = set(release.bundle_files(ROOT))
        pages = [ROOT.parent / 'plugins/README.md', *sorted((ROOT.parent / 'plugins').glob('*/README.md'))]
        linked = set()
        for page in pages:
            self.assertIn(page.relative_to(ROOT.parent).as_posix(), bundled)
            for target in re.findall(r'\]\(([^)]+)\)', page.read_text()):
                relative = target.split('#')[0]
                if not relative or '://' in relative:
                    continue
                path = (page.parent / relative).resolve()
                self.assertTrue(path.is_file(), (page, target))
                linked.add(path)
                if not relative.endswith('.json'):
                    self.assertIn(path.relative_to(ROOT.parent).as_posix(), bundled)
        self.assertTrue(set((ROOT.parent / 'plugins').rglob('SKILL.md')) <= linked)


if __name__ == '__main__':
    unittest.main()
