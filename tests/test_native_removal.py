"""Removal finishes cleanly: it waits for updates, keeps apps open and leaves no menu behind.

Reproduced on Windows 20/10/2026: removal during an update printed "deferred" and
exited 0 without removing anything; after a successful removal the tray menu kept
running; and Settings > Apps had no SCG Router entry to uninstall from.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_native_setup import ROOT, module


class RemovalLockTests(unittest.TestCase):
    def test_removal_waits_for_a_running_update_and_otherwise_fails(self):
        service = module('service')
        with tempfile.TemporaryDirectory() as temporary:
            update = service.install_lock(temporary)
            self.assertTrue(update.__enter__())
            with service.install_lock(temporary, wait=1) as held:
                self.assertFalse(held)
            threading.Timer(0.3, update.__exit__, (None, None, None)).start()
            with service.install_lock(temporary, wait=5) as held:
                self.assertTrue(held)

    def test_busy_uninstall_reports_failure_instead_of_success(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(install_mod, 'platform_backend'), \
                mock.patch.object(install_mod._svc, 'UNINSTALL_WAIT_S', 0), \
                install_mod.install_lock(temporary), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(install_mod.main(['--uninstall', '--home', temporary]), 1)
        self.assertIn('deferred:', out.getvalue())


class RemovedMenuTests(unittest.TestCase):
    def test_removal_marks_the_home_and_a_running_menu_closes(self):
        shortcuts, menu = module('native_shortcuts'), module('desktop_menu')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
            (home / 'installer.json').write_text('{"version":"1.3.7"}')
            startup, real = mock.Mock(), shortcuts.load
            closed = []
            class Input(io.StringIO):
                def write(self, text):
                    # The first status reaches the tray, then removal finishes.
                    with mock.patch.object(shortcuts, 'load', side_effect=lambda name:
                            startup if name == 'desktop_startup' else real(name)), \
                            mock.patch.object(shortcuts.sys, 'platform', 'darwin'):
                        shortcuts.remove(home)
                    return len(text)
                def close(self):
                    closed.append(True)
                    super().close()
            shell = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), poll=lambda: None,
                                    wait=lambda **kwargs: 0)
            with mock.patch.object(menu, '_events'), \
                    mock.patch.object(menu, '_control', return_value=dict(status='Running', clients=[])), \
                    mock.patch.object(menu.subprocess, 'Popen', return_value=shell) as popen:
                self.assertEqual(menu.run_menu(home, home), 0)
                self.assertEqual(closed, [True])
                startup.remove.assert_called_once_with(home)
                self.assertEqual(menu.run_menu(home, home), 0)  # never reopens after removal
                popen.assert_called_once()

    @unittest.skipIf(sys.platform == 'win32', 'the stub menu helper name is POSIX')
    def test_opening_scg_router_after_removal_shows_setup_not_the_menu(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            shutil.copy(ROOT / 'packaging/native_launch.py', home)
            (home / 'setup-current').write_text('r1\n')
            packaging = home / 'setup/r1/router/packaging'
            packaging.mkdir(parents=True)
            (home / 'setup/r1/control').mkdir()
            (home / 'setup/r1/control/scg-router-menu').touch()
            for name in ('desktop_menu', 'native_setup'):
                (packaging / (name + '.py')).write_text('print(%r)\n' % name)
            run = lambda: subprocess.run([sys.executable, str(home / 'native_launch.py')],
                                         capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertEqual(run(), 'desktop_menu')
            (home / module('native_shortcuts').REMOVED).write_text('removed\n')
            self.assertEqual(run(), 'native_setup')


class WindowsEntryTests(unittest.TestCase):
    def test_settings_apps_lists_scg_router_and_removal_takes_only_its_own_entries(self):
        shortcuts = module('native_shortcuts')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, resources = root / 'home', root / 'home/setup/r1'
            (resources / 'runtime/python').mkdir(parents=True)
            (resources / 'runtime/python/pythonw.exe').touch()
            run = mock.Mock()
            with mock.patch.dict(os.environ, {'APPDATA': str(root / 'AppData')}), \
                    mock.patch.object(shortcuts, 'metadata', return_value={'version': '1.3.6'}):
                shortcuts._windows(home, resources, resources / 'runtime/python/python.exe', run)
                installed = run.call_args.args[0][-1]
                shortcuts._windows_remove(home, run)
                removed = run.call_args.args[0][-1]
        for text in ('SCG Router.lnk', 'Uninstall SCG Router.lnk', shortcuts.UNINSTALL_KEY,
                     "'DisplayName' -Value 'SCG Router'", "'DisplayVersion' -Value '1.3.6'",
                     '--action remove', "throw 'ownership'"):
            self.assertIn(text, installed)
        # Removal deletes a shortcut or the Apps entry only when it points at this home.
        self.assertIn('.Arguments.Contains(%s)' % shortcuts._quote(home / 'native_launch.py'), removed)
        self.assertIn('.InstallLocation -eq %s' % shortcuts._quote(home), removed)


class RemovalFlowTests(unittest.TestCase):
    def repair_ui(self, mode):
        owner, dialog, switch = module('repair_ui'), mock.Mock(), mock.Mock()
        receipts = mock.Mock()
        receipts.read_receipt.return_value = {'clients': {'codex': {}, 'claude-desktop': {}}}
        switch.SwitchError = type('SwitchError', (Exception,), {})
        switch.attached_profile.return_value = (None, {'deploymentMode': mode})
        dialog.confirm_result.return_value = False
        owner._load = lambda name: {'codex_config': receipts, 'native_dialog': dialog,
                                    'claude_desktop_switch': switch,
                                    'claude_desktop_platform': mock.Mock()}[name]
        return owner, dialog

    def test_removal_keeps_codex_open_and_closes_claude_only_on_openrouter(self):
        owner, dialog = self.repair_ui('1p')
        self.assertTrue(owner.close_assistants(Path('/home'), removing=True))
        dialog.confirm_result.assert_not_called()
        owner, dialog = self.repair_ui('3p')
        self.assertFalse(owner.close_assistants(Path('/home'), removing=True))
        question = dialog.confirm_result.call_args.args[0]
        self.assertIn('Claude desktop back to your Claude subscription', question)
        self.assertNotIn('Codex', question)

    def test_removal_says_what_to_reopen_what_stays_and_when_an_update_blocks_it(self):
        setup = module('native_setup')
        for stdout, expected, rc in (('deferred: another router operation is in progress\n',
                                      'still updating, so nothing was removed', 1),
                                     ('uninstalled services\n', 'Quit and reopen Codex to finish', 0)):
            with self.subTest(expected=expected):
                dialog, owners = mock.MagicMock(), dict(
                    codex_switch_config=mock.Mock(), repair_ui=mock.Mock(),
                    native_controller=mock.Mock(**{'launcher_source.return_value': Path('/source')}),
                    codex_config=mock.Mock(**{'read_receipt.return_value': {'clients': {'codex': {}}}}))
                dialog.confirm.return_value = True
                run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=stdout))
                with mock.patch.object(setup, 'load', side_effect=owners.__getitem__), \
                        mock.patch.object(setup.subprocess, 'run', run):
                    self.assertEqual(setup._remove(Path('/resources'), Path('/home'), dialog,
                                                   {'runtime_exec': 'python/bin/python3.14'}), rc)
                message = dialog.message.call_args.args[0]
                self.assertIn(expected, message)
                if rc == 0:
                    self.assertIn('Your model key and settings stay in ' + str(Path('/home')), message)
                dialog.Progress.assert_called_once()
                self.assertEqual(dialog.Progress.call_args.kwargs, {'button': 'OK'})
                self.assertIn('--uninstall', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
