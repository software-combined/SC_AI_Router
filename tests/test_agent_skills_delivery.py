"""Plan 179 delivery reaches both clients, from a manual or a scheduled install.

Four gaps kept hosts on their old skills: Claude Code reads a manifest the
router never wrote, Codex refuses to re-point a marketplace name it already
holds from the old Git source, a scheduled job's PATH hides both CLIs and the
node behind codex's `#!/usr/bin/env node`, and a first copy cut short left a
folder without the ownership marker, which every later run refused.
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'router_agent_skills_delivery', ROOT / 'packaging' / 'agent_skills.py')
skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skills)

LAUNCHD_PATH = '/usr/bin:/bin:/usr/sbin:/sbin'  # what launchd gives the update job
REMOVE = ['codex', 'plugin', 'marketplace', 'remove', 'scg-agent-plugins']


class _Client:
    """Both clients' `--json` list answers from fixed data; records each call.

    Like Codex, it stops listing plugins once their marketplace is removed.
    """

    def __init__(self, source=None, marketplaces=None, installed=()):
        self.calls = []
        self.source = source
        self.marketplaces = marketplaces
        self.installed = list(installed)

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if command[2:4] == ['marketplace', 'remove']:
            self.installed = []
        return SimpleNamespace(returncode=0, stdout=self._answer(command), stderr='')

    def _answer(self, command):
        if command[-1] != '--json':
            return ''
        if command[:4] == ['codex', 'plugin', 'marketplace', 'list']:
            return self.marketplaces if self.marketplaces is not None else json.dumps(
                {'marketplaces': [{'name': 'openai-curated', 'root': '/elsewhere'},
                                  {'name': 'scg-agent-plugins', 'root': '/x',
                                   'marketplaceSource': self.source}]})
        if command[0] == 'codex':
            return json.dumps({'installed': [{'pluginId': p['id'], 'enabled': p['enabled']}
                                             for p in self.installed]})
        return json.dumps(self.installed)


def _found(name, path=None):
    # Resolves to the bare name, so recorded commands read as a person types them.
    return name


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / 'home'
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.base = self.tmp / 'scg-agent-plugins'
        self.root = skills.marketplace_root(self.base)
        self.plugins = self.tmp / 'release-plugins'
        for name in ('scg-review', 'scg-finance'):
            for client in ('.codex-plugin', '.claude-plugin'):
                (self.plugins / name / client).mkdir(parents=True)
                (self.plugins / name / client / 'plugin.json').write_text(json.dumps({'name': name}))

    def test_claude_gets_its_own_manifest_for_every_bundled_plugin(self):
        skills.sync({'clients': 'claude'}, ROOT / 'plugins', base=self.base,
                    run=_Client(), which=_found)
        codex = json.loads((self.root / '.agents/plugins/marketplace.json').read_text())
        claude = json.loads((self.root / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(claude['name'], 'scg-agent-plugins')
        self.assertTrue(claude['owner']['name'])
        self.assertEqual([p['name'] for p in claude['plugins']],
                         [p['name'] for p in codex['plugins']])
        self.assertGreater(len(claude['plugins']), 1)
        for entry in claude['plugins']:
            with self.subTest(plugin=entry['name']):
                self.assertEqual(entry['source'], './plugins/' + entry['name'])
                manifest = self.root / entry['source'] / '.claude-plugin' / 'plugin.json'
                self.assertEqual(json.loads(manifest.read_text())['name'], entry['name'])

    def test_codex_moves_off_the_old_git_source_before_adding_the_router_copy(self):
        add = ['codex', 'plugin', 'marketplace', 'add', str(self.root)]
        for url in ('https://github.com/software-combined/SC_AI_Router.git',
                    'https://github.com/software-combined/SC_Unlimited_ai.git',
                    'git@github.com:software-combined/SC_OpenRouter_adapter.git',
                    'https://github.com/Software-Combined/SC_Agent_plugins'):
            with self.subTest(url=url):
                run = _Client({'sourceType': 'git', 'source': url})
                line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                                   run=run, which=_found)
                self.assertIn(REMOVE, run.calls)
                self.assertLess(run.calls.index(REMOVE), run.calls.index(add))
                self.assertIn('codex: 2 plugin(s), old Git source removed', line)
                self.assertNotIn('refused', line)

    def test_codex_leaves_every_other_marketplace_source_alone(self):
        cases = {
            'another owner': _Client({'sourceType': 'git',
                                     'source': 'https://github.com/someone/SC_AI_Router.git'}),
            'a lookalike repo': _Client({'sourceType': 'git', 'source':
                                        'https://github.com/software-combined/SC_AI_Router-fork.git'}),
            'a local checkout': _Client({'sourceType': 'local', 'source': str(ROOT)}),
            'the router copy': _Client({'sourceType': 'local', 'source': str(self.root)}),
            'an unreadable list': _Client(marketplaces='Error: failed to load configuration'),
        }
        for case, run in cases.items():
            with self.subTest(case=case):
                skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                            run=run, which=_found)
                self.assertNotIn(REMOVE, run.calls)
                self.assertIn(['codex', 'plugin', 'marketplace', 'add', str(self.root)],
                              run.calls)

    def test_a_plugin_turned_off_stays_off_in_both_clients(self):
        # Both install commands turn a plugin back on. Codex also moves off the
        # old Git source here, and hides its plugins once that is removed, so
        # the choice has to be read before anything changes.
        installed = [{'id': 'scg-finance@scg-agent-plugins', 'enabled': False},
                     {'id': 'scg-review@scg-agent-plugins', 'enabled': True}]
        git = {'sourceType': 'git',
               'source': 'https://github.com/software-combined/SC_AI_Router.git'}
        for client, verb in (('codex', 'add'), ('claude', 'install')):
            with self.subTest(client=client):
                run = _Client(git, installed=installed)
                line = skills.sync({'clients': client}, self.plugins, base=self.base,
                                   run=run, which=_found)
                self.assertNotIn([client, 'plugin', verb, 'scg-finance@scg-agent-plugins'],
                                 run.calls)
                self.assertIn([client, 'plugin', verb, 'scg-review@scg-agent-plugins'],
                              run.calls)
                self.assertIn(f'{client}: 2 plugin(s), 1 left disabled', line)
                # One list per client: each call may wait up to its timeout.
                self.assertEqual(len([c for c in run.calls if c[2] == 'list']), 1)

    def test_every_client_command_runs_the_resolved_path(self):
        # From PR #354: on Windows an npm client is codex.cmd. which() finds
        # it, but CreateProcess cannot start the bare name, so every call,
        # the list queries included, runs the path which() resolved.
        shim = 'C:\\node\\codex.cmd'
        run = _Client()
        skills.sync({'clients': 'codex'}, self.plugins, base=self.base, run=run,
                    which=lambda name, path=None: shim if name == 'codex' else None)
        self.assertEqual({c[0] for c in run.calls}, {shim})
        self.assertIn([shim, 'plugin', 'marketplace', 'list', '--json'], run.calls)

    def test_the_marker_lands_before_the_first_plugin_copy(self):
        # From PR #353: a first delivery that dies on its very first copy
        # still leaves a folder the router recognises as its own.
        def full(src, dst, *args, **kwargs):
            raise OSError('disk full')

        with patch.object(skills.shutil, 'copytree', full):
            line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                               run=_Client(), which=_found)
        self.assertIn('skipped', line)
        self.assertTrue((self.root / skills.MARKER).exists())
        self.assertFalse((self.root / 'plugins').exists())

    def test_an_interrupted_first_delivery_is_repaired_by_the_next(self):
        # From PR #353: with the marker written last, this partial folder was
        # refused as foreign by every later run, so the host froze.
        real = skills.shutil.copytree
        copies = []

        def flaky(src, dst, *args, **kwargs):
            copies.append(src)
            if len(copies) == 2:
                raise OSError('disk full')
            return real(src, dst, *args, **kwargs)

        with patch.object(skills.shutil, 'copytree', flaky):
            skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                        run=_Client(), which=_found)
        self.assertFalse((self.root / '.agents/plugins/marketplace.json').exists())
        line = skills.sync({'clients': 'codex'}, self.plugins, base=self.base,
                           run=_Client(), which=_found)
        self.assertNotIn('skipped', line)
        manifest = json.loads((self.root / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual([e['name'] for e in manifest['plugins']],
                         ['scg-finance', 'scg-review'])

    @unittest.skipIf(os.name == 'nt', 'shebang scripts are POSIX-only')
    def test_a_scheduled_job_path_still_reaches_both_clients(self):
        # Real subprocess and real which, as the scheduled update runs them.
        # codex is a `#!/usr/bin/env node` script, so the interpreter beside
        # it must resolve too; the fakes stand in for both with a call log.
        bin_dir = self.home / '.local' / 'bin'
        bin_dir.mkdir(parents=True)
        log = self.tmp / 'calls.log'
        (bin_dir / 'scg-test-node').write_text(
            '#!/bin/sh\nname=$(basename "$1"); shift\n'
            f'printf "%s %s\\n" "$name" "$*" >> "{log}"\n'
            'case "$*" in *"marketplace list"*) echo \'{"marketplaces": []}\';; esac\n')
        for client in ('codex', 'claude'):
            (bin_dir / client).write_text('#!/usr/bin/env scg-test-node\n')
        for script in bin_dir.iterdir():
            script.chmod(0o755)
        # A real client elsewhere on this machine could only touch these.
        isolated = {'PATH': LAUNCHD_PATH, 'HOME': str(self.home),
                    'CODEX_HOME': str(self.tmp / 'codex-home'),
                    'CLAUDE_CONFIG_DIR': str(self.tmp / 'claude-home')}
        with patch.dict(os.environ, isolated):
            line = skills.sync({'clients': 'both'}, self.plugins, base=self.base)
        self.assertIn('codex: 2 plugin(s)', line)
        self.assertIn('claude: 2 plugin(s)', line)
        self.assertNotIn('refused', line)
        calls = log.read_text().splitlines()
        self.assertIn(f'codex plugin marketplace add {self.root}', calls)
        self.assertIn('codex plugin add scg-review@scg-agent-plugins', calls)
        self.assertIn(f'claude plugin marketplace add {self.root}', calls)
        self.assertIn('claude plugin install scg-finance@scg-agent-plugins', calls)

    def test_windows_search_adds_no_drive_root_folder(self):
        # On Windows /opt/homebrew/bin and /usr/local/bin would mean C:\opt\... and
        # C:\usr\..., which any local account can create and plant a codex.exe in.
        # The Codex app's own CLI directory is added instead, because that is
        # where an app install keeps codex.exe and never puts it on PATH.
        home_bin = str(Path.home() / '.local' / 'bin')
        local = self.tmp / 'Local'
        build = local / 'OpenAI' / 'Codex' / 'bin' / '0ddb895c950eaeba'
        build.mkdir(parents=True)
        (build / 'codex.exe').write_bytes(b'')
        for name, sep, path, extra in (
                ('nt', ';', r'C:\Windows\System32;C:\Windows', [home_bin, str(build)]),
                ('posix', ':', LAUNCHD_PATH, [home_bin, '/opt/homebrew/bin', '/usr/local/bin'])):
            with self.subTest(os_name=name), patch.object(skills.os, 'name', name), \
                    patch.object(skills.os, 'pathsep', sep), \
                    patch.dict(os.environ, {'PATH': path, 'LOCALAPPDATA': str(local)}):
                self.assertEqual(skills.client_path(), sep.join([path, *extra]))

    def test_windows_search_prefers_the_newest_codex_build(self):
        # The app keeps one directory per build, so the newest one is current.
        local = self.tmp / 'Local'
        base = local / 'OpenAI' / 'Codex' / 'bin'
        old, new = base / 'aaa', base / 'zzz'
        for index, build in enumerate((old, new)):
            build.mkdir(parents=True)
            os.utime(build, (1_000 + index, 1_000 + index))
        found = skills.client_path({'PATH': r'C:\Windows', 'LOCALAPPDATA': str(local)},
                                   os_name='nt')
        self.assertEqual(found.split(os.pathsep)[1:],
                         [str(Path.home() / '.local' / 'bin'), str(new), str(old)])

    def test_windows_search_without_a_codex_tree_adds_nothing(self):
        home_bin = str(Path.home() / '.local' / 'bin')
        found = skills.client_path({'PATH': r'C:\Windows', 'LOCALAPPDATA': str(self.tmp)},
                                   os_name='nt')
        self.assertEqual(found, r'C:\Windows' + os.pathsep + home_bin)


if __name__ == '__main__':
    unittest.main()
