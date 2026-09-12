"""Real bundled router processes and unsigned updates; only systemctl is faked."""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import _install_mod
from tests.test_release import _release_mod


@unix_only
class SystemdRuntimeTests(unittest.TestCase):
    def test_legacy_migration_scheduled_update_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, self.process = Path(tmp), None
            self.home = root / 'router'
            self.commands = []
            env = {'HOME': str(root / 'user'), 'XDG_CONFIG_HOME': str(root / 'config'),
                   'ROUTER_HOME': str(self.home), 'OPENROUTER_API_KEY': 'test-key',
                   # The restart notice is a GUI side effect; this suite must
                   # never pop dialogs (the child installer inherits this).
                   'ROUTER_NO_NOTICE': '1',
                   'ROUTER_NO_KEY_WINDOW': '1',
                   # Deliberate live run: HOME is faked hermetic and only
                   # systemctl is stubbed, so main() may use this home.
                   'ROUTER_LIVE_RUN': '1'}
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
                try:
                    installer = self.prepare(_install_mod())
                    feed_dir = root / 'feed'
                    feed = 'file://' + str(feed_dir / 'latest.json')
                    argv = ['--home', str(self.home), '--python', sys.executable, '--feed', feed]
                    release = _release_mod()
                    def build(number):
                        release.main(['--out', str(feed_dir), '--build', str(number),
                                      '--url-base', 'file://' + str(feed_dir)])
                    build(1)
                    installer.main(argv)
                    first = installer.current_version(self.home)
                    state = installer.ensure_state(self.home)
                    self.assertEqual(installer.health(state)['version'], first)
                    self.stop()
                    current = self.home / 'current'
                    current.unlink()
                    current.symlink_to(self.home / 'releases' / first)
                    self.process = subprocess.Popen([sys.executable, '-m', 'ai_router'],
                        cwd=current, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.assertTrue(installer.wait_version(state, first))
                    build(2)
                    installer.main(argv)
                    second = installer.current_version(self.home)
                    self.assertFalse(current.is_symlink())
                    self.assertNotEqual(first, second)
                    self.assertEqual(installer.health(state)['version'], second)
                    build(3)
                    args = installer.build_parser().parse_args(argv)
                    with mock.patch.dict(os.environ, {'ROUTER_UPDATE_SERVICE': '1'}):
                        installer.do_check_update(args, _sleep=lambda s: None)
                    third = installer.current_version(self.home)
                    self.assertNotEqual(second, third)
                    self.assertEqual(installer.health(state)['version'], third)
                    self.assertIn(third, (self.home / 'logs' / 'update.log').read_text())
                    installer.main(['--home', str(self.home), '--version', second])
                    self.assertEqual(installer.health(state)['version'], second)
                    # A restored pre-Linux release still contains the macOS-only remover.
                    (self.home / 'releases' / second / 'tools' / 'disable.py').write_text(
                        "raise SystemExit('legacy remover calls launchctl')\n")
                    installer.main(['--home', str(self.home), '--uninstall'])
                    self.assertIsNone(self.process)
                    self.assertTrue((self.home / 'mixed-router-state.json').exists())
                    self.assertFalse(any(cmd[0] == 'launchctl' for cmd in self.commands))
                finally:
                    self.stop()

    def prepare(self, installer):
        installer.PLATFORM = 'linux'
        installer._svc.run = self.run_command
        installer.run = self.run_command
        return installer

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait()
                self.process = None

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == 'systemctl':
            if cmd[2] == 'restart':
                self.stop()
                self.process = subprocess.Popen([sys.executable, str(self.home / 'router_launch.py')],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if cmd[2] in ('stop', 'disable') and 'codex-mixed-model-router.service' in cmd:
                self.stop()
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if len(cmd) > 1 and Path(cmd[1]).name == 'install.py':
            spec = importlib.util.spec_from_file_location('downloaded_install', cmd[1])
            child = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(child)
            # Run the real downloaded installer with the same fake OS boundary.
            result = self.prepare(child).main(cmd[2:])
            return subprocess.CompletedProcess(cmd, result, '', '')
        return subprocess.run(cmd, **kwargs)


if __name__ == '__main__':
    unittest.main()
