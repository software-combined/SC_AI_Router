"""Updates, rollbacks and untested platforms never leave a Claude user stuck."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.claude_profile_sync_fixtures import load_helper
from tests.install_fixtures import install_mod
from tests.test_install_lifecycle import _run_install

ROOT = Path(__file__).resolve().parents[1]
desktop = install_mod._desktop_config
# A 0.6 switch helper: no PROFILE_ACTIONS; it records the arguments it ran with.
OLD_SWITCH = ('import sys\nfrom pathlib import Path\n'
              'Path(sys.argv[0]).with_name("ran.txt").write_text(" ".join(sys.argv[1:]))\n')


def fake_switch(installed):
    """Stand in for the switch module: each launcher installs, or is refused."""
    error = type('SwitchError', (Exception,), {})

    def install(_home, _python, action):
        if action not in installed:
            raise error('refused')

    module = SimpleNamespace(SwitchError=error, install_launcher=install,
                             subprocess=SimpleNamespace(SubprocessError=subprocess.SubprocessError),
                             _load=lambda _name: SimpleNamespace(install=lambda *args: None))
    return SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None)), module


class UpdateAndPlatformTests(unittest.TestCase):
    @unix_only  # Same install harness as the other desktop update tests.
    def test_update_keeps_the_saved_profile_after_the_default_moved(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(desktop, '_install_switch_launcher') as launcher:
            home = Path(tmp) / 'router'
            old, new = Path(tmp) / 'Roaming/Claude-3p', Path(tmp) / 'Local/Claude-3p'
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(old)}):
                self.assertEqual(_run_install(self, tmp, home, '1.0.0', '--desktop')[0], 0)
            receipt = install_mod._codex_config.read_receipt(home)['clients']['claude-desktop']
            env = {key: value for key, value in os.environ.items() if key != 'CLAUDE_USER_DATA_DIR'}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(desktop, 'user_data_dir', return_value=new):
                launcher.reset_mock()
                self.assertEqual(_run_install(self, tmp, home, '1.0.1')[0], 0)  # Unattended.
                launcher.assert_called_once()
                with self.assertRaisesRegex(SystemExit, 'different profile'):
                    _run_install(self, tmp, home, '1.0.2', '--desktop')  # An explicit choice.
            self.assertEqual(install_mod._codex_config.read_receipt(home)['clients']['claude-desktop'],
                             receipt)
            self.assertFalse(new.exists())

    def test_windows_and_linux_install_no_launchers_or_session_callback(self):
        for name in ('win32', 'linux'):
            with self.subTest(platform=name), mock.patch.object(desktop.sys, 'platform', name), \
                    mock.patch.object(desktop._ilu, 'spec_from_file_location') as load:
                desktop._install_switch_launcher('/router', '/python')
                load.assert_not_called()

    def test_setup_deletes_only_the_routers_own_old_switch_shim(self):
        own = hashlib.sha256(b'router copy').hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / 'claude_switch_launch.py'
            for content, installed, kept in ((b'router copy', ('switch', 'start'), False),
                                             (b'edited copy', ('switch', 'start'), True),
                                             (b'router copy', ('start',), True)):
                shim.write_bytes(content)
                spec, module = fake_switch(installed)
                with mock.patch.object(desktop, 'OLD_SWITCH_SHIM_SHA256', own), \
                        mock.patch.object(desktop.sys, 'platform', 'darwin'), \
                        mock.patch.object(desktop._ilu, 'spec_from_file_location', return_value=spec), \
                        mock.patch.object(desktop._ilu, 'module_from_spec', return_value=module), \
                        contextlib.redirect_stdout(io.StringIO()):
                    desktop._install_switch_launcher(tmp, '/python')
                self.assertEqual(shim.exists(), kept, (content, installed))


class RollbackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'router'
        old = self.home / 'releases/0.6.140/packaging'
        old.mkdir(parents=True)
        (old / 'claude_desktop_switch.py').write_text(OLD_SWITCH)
        (self.home / 'current').write_text('0.6.140')
        shutil.copyfile(ROOT / 'packaging/claude_profile_launch.py', self.home / 'claude_profile_launch.py')

    def callback(self, cwd=None):
        """Install the session callback, then run its exact command as Claude Code does."""
        config = self.root / 'claude'
        config.mkdir(exist_ok=True)
        load_helper('claude_profile_hook').install(self.home, sys.executable,
                                                   {'CLAUDE_CONFIG_DIR': str(config)})
        command = json.loads((config / 'settings.json').read_text())[
            'hooks']['SessionStart'][0]['hooks'][0]['command']
        return subprocess.run(command, shell=True, cwd=cwd, input='{}', capture_output=True,
                              text=True, timeout=30)

    def test_session_callback_stays_quiet_after_a_rollback_or_removal(self):
        for removed in (False, True):
            if removed:
                (self.home / 'claude_profile_launch.py').unlink()
            answer = self.callback()
            self.assertEqual((answer.returncode, answer.stdout, answer.stderr), (0, '', ''))
            # The callback must never run the older release's plain switch.
            self.assertFalse((self.home / 'releases/0.6.140/packaging/ran.txt').exists())

    def test_session_callback_never_imports_code_from_the_session_folder(self):
        project, marker = self.root / 'project', self.root / 'shadowed'
        project.mkdir()
        (project / 'pathlib.py').write_text('open(%r, "w").close()\n' % str(marker))
        answer = self.callback(cwd=project)
        self.assertEqual((answer.returncode, answer.stdout, answer.stderr), (0, '', ''))
        self.assertFalse(marker.exists())

    def test_switch_claude_uses_the_older_releases_plain_switch(self):
        answer = subprocess.run([sys.executable, str(self.home / 'claude_profile_launch.py'),
                                 '--home', str(self.home), '--action', 'switch'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        ran = self.home / 'releases/0.6.140/packaging/ran.txt'
        self.assertEqual(ran.read_text(), '--home ' + str(self.home))
