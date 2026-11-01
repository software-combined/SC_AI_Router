"""Bootstrap and scheduled updates retain their verified Python interpreter."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import _craft_bundle, install_mod
from tests import test_bootstrap, test_update_channel


class RetainedInterpreterTests(unittest.TestCase):
    @unix_only
    def test_bootstrap_passes_its_retained_python_despite_competing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            rival = Path(tmp) / 'competing'
            rival.mkdir()
            (rival / 'python3.14').symlink_to(sys.executable)
            proc, home = test_bootstrap.BootstrapTests()._full_run(
                tmp, 'stable', path=str(rival) + os.pathsep + os.environ['PATH'])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            argv = json.loads((home / 'installer-argv.txt').read_text())
            self.assertIn('--python', argv)
            self.assertEqual(argv[argv.index('--python') + 1],
                             str(home.resolve() / 'runtime/python/bin/python3.14'))

    def test_running_python_precedes_path_but_explicit_eligible_python_wins(self):
        for explicit, running_version, expected in (
                (None, '3 14', '/retained/python'),
                ('/chosen/python', '3 14', '/chosen/python'),
                (None, '3 9', 'python3.14')):
            tried = []
            def probe(cmd, **kwargs):
                tried.append(cmd[0])
                version = running_version if cmd[0] == '/retained/python' else '3 14'
                return SimpleNamespace(returncode=0, stdout=version + '\n' + cmd[0] + '\n')
            with self.subTest(explicit=explicit, running=running_version), \
                    mock.patch.object(sys, 'executable', '/retained/python'), \
                    mock.patch.object(install_mod._svc, 'run', probe):
                self.assertEqual(install_mod.find_python(explicit), expected)
                self.assertEqual(tried[0], explicit or '/retained/python')

    @unix_only
    def test_existing_repair_reuses_runtime_and_preserves_saved_access_and_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            runtime = home / 'runtime/python/bin/python3.14'
            runtime.parent.mkdir(parents=True)
            runtime.symlink_to(sys.executable)
            for name, value in {'current': '1.2.6.174', 'channel': 'beta',
                    'openrouter.key': 'synthetic-key', 'download-auth.json': '{legacy'}.items():
                (home / name).write_text(value)
            proc, home = test_bootstrap.BootstrapTests()._full_run(tmp, None, sha='0' * 64)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn('/runtimes/', (Path(tmp) / 'argv.log').read_text())
            args = json.loads((home / 'installer-argv.txt').read_text())
            self.assertIn('--repair', args)
            self.assertNotIn('--setup', args)
            self.assertIn('https://feed.example/beta/latest.json', args)
            for name, value in {'channel': 'beta\n', 'openrouter.key': 'synthetic-key',
                                'download-auth.json': '{legacy'}.items():
                self.assertEqual((home / name).read_text(), value)

    @unix_only
    def test_legacy_directory_pointer_gets_repair_and_keeps_the_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            release = home / 'releases/9.9.10'
            release.mkdir(parents=True)
            (home / 'current').symlink_to(release, target_is_directory=True)
            proc, home = test_bootstrap.BootstrapTests()._full_run(tmp, 'stable', land=False)
            args = json.loads((home / 'installer-argv.txt').read_text())
            self.assertIn('--repair', args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((home / 'current').is_symlink())
            self.assertEqual((home / 'channel').read_text(), 'stable\n')

    @unix_only
    def test_a_replacement_runtime_does_not_overwrite_the_old_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            previous = home / 'runtime/python/bin/python3.14'
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b'broken retained interpreter')
            proc, home = test_bootstrap.BootstrapTests()._full_run(tmp, 'stable')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            args = json.loads((home / 'installer-argv.txt').read_text())
            selected = Path(args[args.index('--python') + 1])
            self.assertNotEqual(selected, home.resolve() / 'runtime/python/bin/python3.14')
            self.assertTrue(selected.is_file())
            self.assertEqual(previous.read_bytes(), b'broken retained interpreter')

    def test_scheduled_child_receives_the_updaters_interpreter(self):
        fixture = test_update_channel.UpdateBackoffTests()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as tmp:
            home = fixture._home(tmp)
            blob, latest = _craft_bundle('9.9.9')
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                return SimpleNamespace(returncode=1, stdout='', stderr='synthetic refusal')
            fixture._check(home, blob, latest, [], run=run)
            command = next(cmd for cmd in calls if len(cmd) > 1 and cmd[1].endswith('install.py'))
            self.assertIn('--python', command)
            self.assertEqual(command[command.index('--python') + 1], sys.executable)
            self.assertNotIn('--repair', command)
