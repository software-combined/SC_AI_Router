"""The Switch Codex app: built, refreshed and removed with the Codex attachment.

Every subprocess is faked except the real tools/disable.py, which runs with a
temporary HOME; no dialog is shown and no app is opened. The app is built on
a Mac for an attached subscription install whose ChatGPT app is affected or
that is switched now, never removed while switched, removed on detach, and
runs a stable launcher that follows the current release.
"""
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = _load('codex_switch_app_test', 'packaging/codex_switch_app.py')
launcher = _load('codex_switch_launch_test', 'packaging/codex_switch_launch.py')
blocks = app._blocks
PYTHON = '/opt/router python/python3.14'
AFFECTED = (26, 917, 51856)


@unix_only
class SwitchCodexAppTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home, self.config = self.root / 'router', self.root / 'codex' / 'config.toml'
        self.home.mkdir()
        self.config.parent.mkdir()
        self.target = self.root / 'Applications' / 'Switch Codex.app'
        self.version = AFFECTED
        self.calls = []
        for patcher in (mock.patch.object(app._offer, 'APP', self.target),
                        mock.patch.object(app._offer, 'installed', lambda: self.version),
                        mock.patch.dict(os.environ, {'HOME': str(self.root)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.attach('subscription')

    def attach(self, mode):
        state = {'port': 4321, 'token': 'tok', 'openai_mode': mode}
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = blocks.build(self.home, state, mode, False, 'default')
        self.config.write_text(block + '\nowner_setting = 1\n')
        blocks._codex.write_receipt(self.home, self.config, block, None, mode, '')

    def run_tool(self, argv, **kwargs):
        self.calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def sync(self, platform_name='darwin', run=None):
        app.sync(self.home, PYTHON, platform_name, run=run or self.run_tool)

    def info(self):
        return plistlib.loads((self.target / 'Contents' / 'Info.plist').read_bytes())

    def test_builder_writes_an_owned_app_running_the_home_launcher(self):
        self.sync()
        info = self.info()
        self.assertEqual({key: info[key] for key in (
            'CFBundleIdentifier', 'CFBundleName', 'CFBundleExecutable', 'CFBundleIconFile',
            'LSUIElement', app.HOME_KEY)}, {
            'CFBundleIdentifier': 'com.softwarecombined.router.codex-switch',
            'CFBundleName': 'Switch Codex', 'CFBundleExecutable': 'Switch Codex',
            'CFBundleIconFile': 'router.icns', 'LSUIElement': True, app.HOME_KEY: str(self.home)})
        executable = self.target / 'Contents' / 'MacOS' / 'Switch Codex'
        self.assertEqual(executable.read_text(), "#!/bin/sh\nexec '%s' %s\n"
                         % (PYTHON, self.home / app.LAUNCHER))
        self.assertTrue(executable.stat().st_mode & 0o100)
        self.assertEqual((self.home / app.LAUNCHER).read_bytes(),
                         (ROOT / 'packaging' / app.LAUNCHER).read_bytes())
        icon = str(app._platform.ICON)
        self.assertEqual([call[0] for call in self.calls],
                         ['/usr/bin/sips', '/usr/bin/sips', '/usr/bin/iconutil'])
        self.assertEqual([call[4] for call in self.calls[:2]], [icon, icon])
        self.assertTrue(self.calls[2][-1].endswith('Contents/Resources/router.icns'))
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])  # staging gone

    def test_an_app_it_does_not_own_is_left_alone(self):
        (self.target / 'Contents').mkdir(parents=True)
        foreign = plistlib.dumps({'CFBundleIdentifier': 'com.example.other'})
        (self.target / 'Contents' / 'Info.plist').write_bytes(foreign)
        with mock.patch('builtins.print') as said:
            self.sync()
        self.assertIn('already exists', said.call_args.args[0])
        self.assertEqual((self.target / 'Contents' / 'Info.plist').read_bytes(), foreign)
        self.version = (26, 900)
        self.sync()
        self.assertTrue(self.target.exists())  # never removed either
        # An app with our bundle id that another router home built stays too.
        self.target.rename(self.root / 'foreign.app')
        other = self.root / 'other-home'
        other.mkdir()
        app._platform.install_mac_app(self.target, app.BUNDLE_ID, PYTHON, other, app.LAUNCHER,
                                      plist={app.HOME_KEY: str(other)}, run=self.run_tool)
        self.assertFalse(app.remove(self.home))
        self.sync()
        self.assertEqual(self.info()[app.HOME_KEY], str(other))

    def test_build_conditions(self):
        for label, version, mode, want in (
                ('affected build', AFFECTED, 'subscription', True),
                ('newer build', (26, 924, 22138), 'subscription', True),
                ('older build', (26, 900, 1), 'subscription', False),
                ('no ChatGPT app', None, 'subscription', False),
                ('no subscription', AFFECTED, 'none', False)):
            with self.subTest(label):
                self.attach('subscription')
                self.version = AFFECTED
                self.sync()  # an owned app from an earlier install is there first
                self.attach(mode)
                self.version = version
                self.sync()
                self.assertEqual(self.target.exists(), want)
        self.attach('subscription')
        self.version = AFFECTED
        self.sync(platform_name='linux')  # nothing outside macOS
        self.assertFalse(self.target.exists())
        with mock.patch.dict(os.environ, {'HOME': str(self.root / 'elsewhere')}):
            self.sync()  # HOME moved after the app's place was named: never written
        self.assertFalse(self.target.exists())
        self.sync()
        self.assertTrue(self.target.exists())
        (self.home / 'activation.json').unlink()  # Codex no longer attached
        self.sync()
        self.assertFalse(self.target.exists())

    def test_the_app_stays_while_codex_is_switched(self):
        self.version = (26, 900, 1)
        blocks.switch(self.home, 'switched')
        self.sync()
        self.assertTrue(self.target.exists())  # built for an older build: it is the way back
        self.attach('none')
        blocks.switch(self.home, 'switched')
        self.sync()
        self.assertTrue(self.target.exists())

    def test_a_failed_build_never_fails_an_install(self):
        def failing(argv, **kwargs):
            raise subprocess.CalledProcessError(1, argv)
        with mock.patch('builtins.print') as said:
            self.sync(run=failing)
        self.assertEqual(said.call_count, 1)
        self.assertIn('Run setup again', said.call_args.args[0])
        self.assertFalse(self.target.exists())

    def test_detach_removes_the_owned_app_but_not_while_switched(self):
        self.sync()
        env = dict(os.environ, HOME=str(self.root), ROUTER_HOME=str(self.home),
                   ROUTER_RESTORE_ONLY='1')
        remover = [sys.executable, str(ROOT / 'tools' / 'disable.py')]
        blocks.switch(self.home, 'switched')
        refused = subprocess.run(remover, capture_output=True, text=True, env=env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertTrue(self.target.exists())
        blocks.switch(self.home, 'switched_back')
        done = subprocess.run(remover, capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.target.exists())

    def test_installs_sync_the_app_with_the_router_python(self):
        from tests.install_fixtures import install_mod
        from tests.test_install_config import _install
        seen = []
        with mock.patch.object(install_mod._client_choice._app, 'sync',
                               lambda home, python: seen.append((home, python))):
            _install(self, str(self.root), self.home, '1.0.0')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], self.home)
        self.assertTrue(seen[0][1])


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.shown = []
        patcher = mock.patch.object(launcher.sys, 'argv', ['launcher'])
        patcher.start()
        self.addCleanup(patcher.stop)

    def release(self, version, helper=None):
        packaging = self.home / 'releases' / version / 'packaging'
        packaging.mkdir(parents=True)
        (self.home / 'current').write_text(version + '\n')
        if helper is not None:
            (packaging / 'codex_desktop_switch.py').write_text(helper)

    def run_launcher(self):
        return launcher.main(self.home, run=lambda argv, **kwargs: self.shown.append(argv))

    def test_runs_the_current_release_switch_flow(self):
        record = self.home / 'argv.json'
        self.release('1.0.0', 'import json, sys\nopen(%r, "w").write(json.dumps(sys.argv))\n'
                     % str(record))
        self.assertEqual(self.run_launcher(), 0)
        helper = self.home / 'releases' / '1.0.0' / 'packaging' / 'codex_desktop_switch.py'
        self.assertEqual(json.loads(record.read_text()), [str(helper), '--home', str(self.home)])
        self.assertEqual(self.shown, [])

    def test_an_older_or_broken_release_gets_one_plain_message(self):
        for label, prepare, message in (
                ('no current release', lambda: None, launcher.OLDER),
                ('older release', lambda: self.release('0.6.140'), launcher.OLDER),
                ('broken release', lambda: self.release('1.0.1', 'raise ImportError("x")\n'),
                 launcher.BROKEN)):
            with self.subTest(label):
                self.shown.clear()
                prepare()
                self.assertEqual(self.run_launcher(), 1)
                script = self.shown[0][-1]
                self.assertIn(json.dumps(message), script)
                self.assertIn('with title "SCG Router" buttons {"Cancel"}', script)


if __name__ == '__main__':
    unittest.main()
