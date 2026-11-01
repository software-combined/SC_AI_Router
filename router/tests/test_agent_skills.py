"""Plan 179: the router delivers the SCG agent skills without git.

Proves the shipped bundle carries every plugin, that a local marketplace is
materialised and registered only for attached clients, that a foreign
directory is never clobbered, and that a superseded runner is preserved
rather than deleted.
"""
import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


skills = _load('router_agent_skills', 'packaging/agent_skills.py')
release = _load('router_release', 'packaging/release.py')


class _Run:
    """Records commands instead of executing them."""

    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=self.returncode, stdout='', stderr='')


def _which(present):
    return lambda name, path=None: ('/usr/bin/' + name) if name in present else None


class AgentSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.enterContext(patch.dict('os.environ', {'XDG_CONFIG_HOME': ''}))
        self.enterContext(patch.object(skills.os, 'getuid', return_value=501, create=True))
        self.plist = self.home / 'Library/LaunchAgents' / (skills.GIT_UPDATER_LABEL + '.plist')
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text('stale schedule')
        self.base = Path(self.tmp.name) / 'scg-agent-plugins'
        self.plugins = Path(self.tmp.name) / 'release-plugins'
        for name in ('scg-review', 'scg-finance'):
            manifest = self.plugins / name / '.codex-plugin'
            manifest.mkdir(parents=True)
            (manifest / 'plugin.json').write_text(json.dumps({'name': name}))
            skill = self.plugins / name / 'skills' / name
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: %s\n---\n' % name)

    def test_bundle_carries_every_plugin_manifest_and_skill(self):
        bundled = set(release.bundle_files(ROOT))
        for plugin in skills.plugin_sources(ROOT.parent / 'plugins').values():
            rel = plugin.relative_to(ROOT.parent).as_posix()
            with self.subTest(plugin=plugin.name):
                self.assertIn(rel + '/.codex-plugin/plugin.json', bundled)
                self.assertIn(rel + '/.claude-plugin/plugin.json', bundled)
                self.assertTrue([n for n in bundled if n.startswith(rel + '/skills/')])
                # Ship setup and export tools, without the retired git updater.
                self.assertEqual(
                    sorted(n for n in bundled if n.startswith(rel + '/scripts/')),
                    sorted(rel + '/scripts/' + name for name in ('setup.py', 'export_review.py')
                           if (plugin / 'scripts' / name).is_file()))

    def test_every_bundled_skill_link_resolves_inside_the_bundle(self):
        bundled = set(release.bundle_files(ROOT))
        checked = 0
        for name in sorted(bundled):
            if not name.endswith('/SKILL.md'):
                continue
            text = release.source_file(ROOT, name).read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                path = target.split('#')[0]
                if not path or '://' in path:
                    continue
                resolved = ((ROOT / name).parent / path).resolve().relative_to(ROOT).as_posix()
                checked += 1
                with self.subTest(link=target):
                    self.assertIn(resolved, bundled)
        self.assertGreater(checked, 0, 'no bundled skill links were checked')

    def test_marketplace_is_written_and_registered_for_an_attached_client(self):
        run = _Run()
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=run, which=_which({'codex'}))
        root = skills.marketplace_root(self.base)
        manifest = json.loads((root / '.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['name'], 'scg-agent-plugins')
        self.assertEqual([e['name'] for e in manifest['plugins']],
                         ['scg-finance', 'scg-review'])
        self.assertTrue((root / 'plugins/scg-review/skills/scg-review/SKILL.md').is_file())
        self.assertIn('codex', line)
        self.assertIn(['/usr/bin/codex', 'plugin', 'marketplace', 'add', str(root)], run.calls)

    def test_service_only_host_writes_nothing_and_calls_no_client(self):
        run = _Run()
        line = skills.sync({'clients': 'none'}, self.plugins, base=self.base,
                           run=run, which=_which({'codex', 'claude'}))
        self.assertEqual(run.calls, [])
        self.assertFalse(skills.marketplace_root(self.base).exists())
        self.assertIn('no attached client', line)

    def test_a_codex_host_never_invokes_the_claude_binary(self):
        run = _Run()
        skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                    run=run, which=_which({'codex', 'claude'}))
        self.assertEqual({c[0] for c in run.calls}, {'/usr/bin/codex'})

    def test_a_foreign_directory_is_left_exactly_as_it_is(self):
        root = skills.marketplace_root(self.base)
        root.mkdir(parents=True)
        (root / 'someone-elses-file').write_text('keep me')
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Run(), which=_which({'codex'}))
        self.assertEqual((root / 'someone-elses-file').read_text(encoding='utf-8'), 'keep me')
        self.assertFalse((root / '.agents').exists())
        self.assertFalse((root / skills.MARKER).exists())
        self.assertIn('skipped', line)

    def test_a_marketplace_sync_failure_reports_the_cause_and_path(self):
        root = skills.marketplace_root(self.base)
        root.mkdir(parents=True)
        (root / 'someone-elses-file').write_text('keep me')
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Run(), which=_which({'codex'}))
        self.assertIn('skipped', line)
        self.assertIn('not router-owned', line)
        self.assertIn(str(root), line)

    def test_a_refused_registration_reports_the_command_and_error(self):
        def refuse(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='',
                                   stderr='Error: plugin manifest invalid')
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=refuse, which=_which({'codex'}))
        self.assertIn('refused', line)
        self.assertIn('codex plugin add scg-review@scg-agent-plugins', line)
        self.assertIn('plugin manifest invalid', line)

    def test_a_registration_exec_error_reports_its_cause(self):
        def boom(command, **kwargs):
            raise OSError('codex binary vanished')
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=boom, which=_which({'codex'}))
        self.assertIn('OSError', line)
        self.assertIn('codex binary vanished', line)

    def test_a_refusal_detail_is_collapsed_to_one_bounded_line(self):
        def refuse(command, **kwargs):
            if command[2:4] == ['marketplace', 'add']:
                return SimpleNamespace(returncode=1, stdout='',
                                       stderr='x' * 500 + '\nsecond line')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=refuse, which=_which({'codex'}))
        self.assertIn('1 refused', line)
        self.assertNotIn('\n', line)
        self.assertNotIn('second', line)
        self.assertLess(len(line), 500)

    def test_a_refusal_keeps_only_the_first_error_line(self):
        # Codex 0.153 quotes a bad config value in its cause chain; a
        # coloured summary must not bring terminal escapes into the log.
        def refuse(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr=(
                '\x1b[31mError:\x1b[0m failed to load bootstrap configuration\n'
                '\nCaused by:\n    invalid type: string "GH_PAT=stand-in-config-value",'
                ' expected a map\n    in `mcp_servers.github.env`\n'))
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=refuse, which=_which({'codex'}))
        self.assertIn('failed to load bootstrap configuration', line)
        self.assertNotIn('stand-in-config-value', line)
        self.assertNotIn('\x1b', line)

    def test_a_refusal_line_survives_a_windows_ansi_pipe(self):
        # Claude Code 2.1.283 opens refusals with U+2718; a cp1252 pipe refuses it.
        def refuse(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr=(
                '\u2718 Failed to install plugin "scg-review@scg-agent-plugins"'))
        base = Path(self.tmp.name) / '\u0141ukasz' / 'scg-agent-plugins'
        line = skills.sync({'clients': 'claude'}, self.plugins, base=base,
                           run=refuse, which=_which({'claude'}))
        line.encode('cp1252')  # strict: an unescaped character raises here
        line.encode('ascii')
        self.assertIn('\\u2718 Failed to install plugin', line)
        self.assertIn('\\u0141ukasz', line)

    def test_a_superseded_runner_is_preserved_not_deleted(self):
        self.base.mkdir(parents=True)
        runner = self.base / 'updater.py'
        runner.write_text('stale runner')
        digest = hashlib.sha256(runner.read_bytes()).hexdigest()
        original = skills.LEGACY_RUNNERS
        skills.LEGACY_RUNNERS = (digest,)
        self.addCleanup(setattr, skills, 'LEGACY_RUNNERS', original)
        line = skills.retire_git_updater(base=self.base, run=_Run(),
                                         which=_which({'launchctl'}))
        self.assertFalse(runner.exists())
        self.assertEqual((self.base / 'updater.py.migrated.0').read_text(encoding='utf-8'), 'stale runner')
        self.assertFalse(self.plist.exists())
        self.assertEqual(
            self.plist.with_name(self.plist.name + '.migrated.0').read_text(encoding='utf-8'), 'stale schedule')
        self.assertIn('retired', line)

    def test_an_unrecognised_runner_is_left_in_place(self):
        self.base.mkdir(parents=True)
        runner = self.base / 'updater.py'
        runner.write_text('not ours')
        line = skills.retire_git_updater(base=self.base, run=_Run(), which=_which(set()))
        self.assertTrue(runner.exists())
        self.assertEqual(self.plist.read_text(encoding='utf-8'), 'stale schedule')
        self.assertIn('unrecognised', line)

    def test_a_missing_plugin_tree_is_a_no_op(self):
        line = skills.sync({'clients': 'codex'}, self.plugins / 'nope',
                           base=self.base, run=_Run(), which=_which({'codex'}))
        self.assertIn('bundle carries none', line)
        self.assertFalse(skills.marketplace_root(self.base).exists())

    def test_an_interrupted_copy_leaves_the_previous_tree_and_no_manifest(self):
        # A first pass lands a good tree.
        skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                    run=_Run(), which=_which({'codex'}))
        root = skills.marketplace_root(self.base)
        good = (root / 'plugins/scg-review/skills/scg-review/SKILL.md').read_text(encoding='utf-8')
        (root / '.agents/plugins/marketplace.json').unlink()
        # A second pass dies part way through the copy loop.
        calls = {'n': 0}
        real = skills.shutil.copytree

        def flaky(src, dst, *a, **k):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('disk full')
            return real(src, dst, *a, **k)

        skills.shutil.copytree = flaky
        self.addCleanup(setattr, skills.shutil, 'copytree', real)
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Run(), which=_which({'codex'}))
        self.assertIn('skipped', line)
        # The manifest is the client's entry point, so it must not exist yet.
        self.assertFalse((root / '.agents/plugins/marketplace.json').exists())
        self.assertEqual(
            (root / 'plugins/scg-review/skills/scg-review/SKILL.md').read_text(encoding='utf-8'), good)

    def test_the_git_fallback_is_kept_when_no_client_accepts(self):
        self.base.mkdir(parents=True)
        runner = self.base / 'updater.py'
        runner.write_text('stale runner')
        digest = hashlib.sha256(runner.read_bytes()).hexdigest()
        original = skills.LEGACY_RUNNERS
        skills.LEGACY_RUNNERS = (digest,)
        self.addCleanup(setattr, skills, 'LEGACY_RUNNERS', original)
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Run(returncode=1), which=_which({'codex'}))
        self.assertTrue(runner.exists())
        self.assertEqual(self.plist.read_text(encoding='utf-8'), 'stale schedule')
        self.assertIn('kept', line)

    def test_the_git_fallback_is_retired_once_a_client_accepts(self):
        self.base.mkdir(parents=True)
        runner = self.base / 'updater.py'
        runner.write_text('stale runner')
        digest = hashlib.sha256(runner.read_bytes()).hexdigest()
        original = skills.LEGACY_RUNNERS
        skills.LEGACY_RUNNERS = (digest,)
        self.addCleanup(setattr, skills, 'LEGACY_RUNNERS', original)
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Run(), which=_which({'codex', 'launchctl'}))
        self.assertFalse(runner.exists())
        self.assertFalse(self.plist.exists())
        self.assertEqual(
            self.plist.with_name(self.plist.name + '.migrated.0').read_text(encoding='utf-8'), 'stale schedule')
        self.assertIn('retired', line)


if __name__ == '__main__':
    unittest.main()
