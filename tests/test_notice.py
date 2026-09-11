"""Restart notice: staging, dialog construction, and the release surface.

MacOS here means AppleScript, Windows a WinForms/PowerShell dialog and
Linux zenity; no test in this module launches a real dialog.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]


def _notice_mod():
    spec = importlib.util.spec_from_file_location(
        'router_notice', _ROOT / 'packaging' / 'notice.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notice_mod = _notice_mod()

MSG = ('SCG router updated to 1.0.1. '
       'Quit and reopen Codex to use the new models.')


class RecordTests(unittest.TestCase):
    def test_fresh_install_stages_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertFalse(notice_mod.record(home, None, '1.0.1'))
            self.assertFalse((home / 'update-notice.json').exists())

    def test_same_version_stages_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertFalse(notice_mod.record(home, '1.0.1', '1.0.1'))
            self.assertFalse((home / 'update-notice.json').exists())

    def test_version_change_stages_pending_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertTrue(notice_mod.record(home, '1.0.0', '1.0.1'))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['version'], '1.0.1')
            self.assertNotIn('shown', doc)

    def test_shown_version_is_not_restaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '1.0.1', 'shown': True,
                            'at': '2026-09-11T00:00:00+00:00'}))
            self.assertFalse(notice_mod.record(home, '1.0.0', '1.0.1'))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertTrue(doc['shown'])
            self.assertEqual(doc['version'], '1.0.1')

    def test_open_dialog_pid_is_carried_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '1.0.1', 'shown': True, 'pid': 4321}))
            self.assertTrue(notice_mod.record(home, '1.0.1', '1.0.2'))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['version'], '1.0.2')
            self.assertEqual(doc['pid'], 4321)
            self.assertNotIn('shown', doc)

    def test_dialog_pid_must_be_a_positive_int(self):
        for bogus in (None, True, 0, -3, '4321'):
            self.assertIsNone(notice_mod._dialog_pid({'pid': bogus}))
        self.assertIsNone(notice_mod._dialog_pid(None))

    def test_write_failure_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'missing-parent' / 'home'
            self.assertFalse(notice_mod.record(home, '1.0.0', '1.0.1'))


class DialogCommandTests(unittest.TestCase):
    def test_darwin_uses_osascript_dialog(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name)
        self.assertEqual(cmd[0], 'osascript')
        script = cmd[cmd.index('-e') + 1]
        self.assertIn(MSG, script)
        self.assertIn('buttons {"Later", "Quit and reopen"}', script)
        self.assertIn('default button "Quit and reopen"', script)
        self.assertIn('cancel button "Later"', script)
        self.assertIn('SCG Router', script)

    def test_darwin_restart_quits_and_relaunches_codex(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name)
        script = cmd[cmd.index('-e') + 1]
        self.assertIn('if answer is "Quit and reopen" then', script)
        self.assertIn(
            'tell application id "com.openai.codex" to quit', script)
        self.assertIn('do shell script "open -b com.openai.codex"', script)

    @unittest.skipUnless(sys.platform == 'darwin',
                         'compiles AppleScript; macOS only')
    def test_darwin_script_compiles(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name,
            icon='/bundle/router-icon.png')
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run(
                ['osacompile', '-e', cmd[cmd.index('-e') + 1],
                 '-o', tmp + '/notice.scpt'],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    @unittest.skipUnless(sys.platform == 'darwin',
                         'compiles AppleScript; macOS only')
    def test_darwin_script_compiles_with_a_non_ascii_path(self):
        # AppleScript has no unicode escape, so an accented home path must
        # reach the script as raw UTF-8 rather than json-escaped text.
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name,
            icon='/Users/jos\u00e9/router-icon.png')
        script = cmd[cmd.index('-e') + 1]
        self.assertIn('/Users/jos\u00e9/router-icon.png', script)
        self.assertNotIn('u00e9', script)
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run(
                ['osacompile', '-e', script, '-o', tmp + '/notice.scpt'],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_darwin_without_osascript_is_none(self):
        self.assertIsNone(notice_mod.dialog_command(
            '1.0.1', platform_name='darwin', which=lambda name: None))

    def test_darwin_uses_the_bundled_icon(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name,
            icon='/bundle/router-icon.png')
        script = cmd[cmd.index('-e') + 1]
        self.assertIn(
            'with icon (POSIX file "/bundle/router-icon.png")', script)

    def test_missing_icon_falls_back_to_the_note_icon(self):
        with mock.patch.object(notice_mod, 'ICON',
                               Path('/no/such/router-icon.png')):
            cmd = notice_mod.dialog_command(
                '1.0.1', platform_name='darwin',
                which=lambda name: '/usr/bin/' + name)
        script = cmd[cmd.index('-e') + 1]
        self.assertIn('with icon note', script)

    def test_linux_prefers_zenity(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='linux',
            which=lambda name: '/usr/bin/' + name
            if name == 'zenity' else None)
        self.assertEqual(cmd[0], 'zenity')
        self.assertIn('--ok-label=Later', cmd)
        self.assertTrue(any(MSG in part for part in cmd))

    def test_linux_zenity_uses_the_icon_when_given(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='linux',
            which=lambda name: '/usr/bin/' + name
            if name == 'zenity' else None,
            icon='/bundle/router-icon.png')
        self.assertIn('--window-icon=/bundle/router-icon.png', cmd)

    def test_linux_offers_restart_when_the_app_is_installed(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='linux',
            which=lambda name: '/usr/bin/' + name)
        self.assertEqual(cmd[:2], ['sh', '-c'])
        self.assertIn('pkill -x chatgpt', cmd[2])
        self.assertIn('setsid -f chatgpt', cmd[2])
        dialog = cmd[cmd.index('zenity'):]
        self.assertEqual(dialog[1], '--question')
        self.assertIn('--ok-label=Quit and reopen', dialog)
        self.assertIn('--cancel-label=Later', dialog)
        # The dialog argv must stay separate list items, never re-parsed.
        self.assertIn('--text=' + MSG, dialog)

    def test_linux_falls_back_to_notify_send(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='linux',
            which=lambda name: '/usr/bin/' + name
            if name == 'notify-send' else None)
        self.assertEqual(cmd[:2], ['notify-send', 'SCG Router'])
        self.assertIn(MSG, cmd)

    def test_linux_without_tools_is_none(self):
        self.assertIsNone(notice_mod.dialog_command(
            '1.0.1', platform_name='linux', which=lambda name: None))

    def test_win32_uses_powershell_form(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='win32',
            which=lambda name: r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
            if name == 'powershell' else None)
        self.assertIn('powershell', cmd[0].lower())
        script = cmd[cmd.index('-Command') + 1]
        self.assertIn('$b.Text = \'Later\'', script)
        self.assertIn('$r.Text = \'Quit and reopen\'', script)
        self.assertIn('SCG Router', script)
        self.assertIn(MSG, script)

    def test_win32_restart_closes_and_relaunches_the_app(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='win32',
            which=lambda name: r'C:\powershell.exe')
        script = cmd[cmd.index('-Command') + 1]
        self.assertIn("$f.Tag = 'reopen'", script)
        self.assertIn("if ($f.Tag -eq 'reopen')", script)
        # The Codex desktop app is an MSIX package, so it is relaunched
        # through its package identity, not an executable path.
        self.assertIn("Get-AppxPackage -Name 'OpenAI.Codex'", script)
        self.assertIn("$pkg.PackageFamilyName + '!' + $entry.Id", script)
        self.assertIn("Get-StartApps", script)
        self.assertIn("shell:AppsFolder", script)
        self.assertIn('CloseMainWindow()', script)
        self.assertIn('Stop-Process -Id $p.Id -Force', script)

    def test_win32_restart_is_scoped_to_that_package(self):
        # A host with only the Codex CLI must not lose it: nothing is quit
        # by process name, and the whole quit block is inside `if ($pkg)`.
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='win32',
            which=lambda name: r'C:\powershell.exe')
        script = cmd[cmd.index('-Command') + 1]
        self.assertNotIn('Get-Process -Name Codex', script)
        self.assertNotIn("Get-Process -Name ChatGPT", script)
        self.assertIn('$_.Path.StartsWith($root', script)
        head, _, tail = script.partition('if ($pkg) {')
        self.assertIn('Stop-Process', tail)
        self.assertNotIn('Stop-Process', head)

    def test_win32_without_powershell_is_none(self):
        self.assertIsNone(notice_mod.dialog_command(
            '1.0.1', platform_name='win32', which=lambda name: None))

    def test_unknown_platform_is_none(self):
        self.assertIsNone(notice_mod.dialog_command(
            '1.0.1', platform_name='plan9',
            which=lambda name: '/usr/bin/' + name))


class ReleaseBundleTests(unittest.TestCase):
    def test_release_bundle_contains_notice_and_icon(self):
        root = _ROOT
        spec = importlib.util.spec_from_file_location(
            'router_release', root / 'packaging' / 'release.py')
        release_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_mod)
        self.assertIn('packaging/notice.py',
                      release_mod.bundle_files(root))
        self.assertIn('packaging/assets/router-icon.png',
                      release_mod.bundle_files(root))
        self.assertTrue(
            (root / 'packaging' / 'assets' / 'router-icon.png').is_file())




if __name__ == '__main__':
    unittest.main()
