"""Executed platform boundaries using isolated app and process fixtures."""
import importlib.util
import base64
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'claude_desktop_platform_test', ROOT / 'packaging/claude_desktop_platform.py')
platform = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(platform)


def result(stdout='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)


class PlatformHarness:
    """Strict command boundary: unknown or unsafe commands fail the test."""
    def __init__(self, name, identity, snapshots):
        self.name, self.identity = name, identity
        self.snapshots, self.commands = iter(snapshots), []

    def __call__(self, argv, **kwargs):
        assert 0 < kwargs['timeout'] <= 120
        self.commands.append(argv)
        script = argv[-1]
        if argv[0] == '/bin/ps' or 'Get-CimInstance Win32_Process' in script:
            rows = next(self.snapshots)
            if isinstance(rows, Exception):
                raise rows  # The probe itself failed or timed out.
            if self.name == 'win32':
                assert 'GetOwnerSid' in script and 'CreationDate' in script
                return result(json.dumps(rows))
            return result('\n'.join('%s %s %s %s %s %s' % (
                r['pid'], r['parent'], r['user'], r['born'], r.get('state', 'S'), r['exe']) for r in rows))
        if argv[0] == '/usr/bin/osascript' and script.endswith(' to quit'):
            return result()
        if 'CloseMainWindow()' in script:
            assert '$p.Path -ne ' in script
            assert "$c.CreationDate.ToString('o') -ne $births[$n]" in script
            assert 'GetOwnerSid' in script and '$o.Sid -ne ' in script
            assert 'Stop-Process' not in script and 'taskkill' not in script
            return result()
        if argv[0] == 'zenity':
            assert '--cancel-label' in argv and 'Cancel' in argv
            return result()
        raise AssertionError('Unexpected platform command: ' + repr(argv))


class DesktopPlatformTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.identity = dict(root='/apps/Claude.app', exe='/apps/Claude.app/Claude', user='501', app='Claude!App')

    def row(self, pid=10, parent=1, exe=None, born='Mon Sep 28 10:00:00 2026'):
        return dict(pid=pid, parent=parent, user='501', born=born,
                    exe=exe or self.identity['exe'])

    def stop(self, name, snapshots, timeout=1):
        harness = PlatformHarness(name, self.identity, snapshots)
        with mock.patch.object(platform, 'app_identity', return_value=self.identity), \
                mock.patch.object(platform.time, 'sleep'), \
                mock.patch.object(platform.time, 'monotonic', return_value=0):  # Only timeout=0 expires.
            answer = platform.request_stop(name, run=harness, timeout=timeout)
        return answer, harness.commands

    def test_all_platforms_wait_for_reparented_descendant_after_main_exits(self):
        for name in ('darwin', 'win32', 'linux'):
            with self.subTest(platform=name):
                main, child = self.row(), self.row(11, 10, '/tools/session-writer')
                orphan = dict(child, parent=1)
                answer, commands = self.stop(name, [[main, child], [orphan], []])
                self.assertTrue(answer)
                self.assertEqual(sum(c[0] == '/bin/ps' or 'Get-CimInstance Win32_Process' in c[-1]
                                     for c in commands), 3)

    def test_live_child_timeout_never_force_kills(self):
        for name in ('darwin', 'win32', 'linux'):
            main, child = self.row(), self.row(11, 10, '/tools/session-writer')
            answer, commands = self.stop(name, [[main, child], [dict(child, parent=1)]], timeout=0)
            self.assertFalse(answer)
            self.assertNotIn('kill', str(commands).lower())

    def test_named_claude_descendant_is_verified_before_unknown_writer_refusal(self):
        for name in ('darwin', 'win32', 'linux'):
            with self.subTest(platform=name):
                main, child = self.row(), self.row(11, 10, '/runtime/claude')
                answer, _ = self.stop(name, [[child, main], [dict(child, parent=1)], []])
                self.assertTrue(answer)

    def test_macos_browser_host_does_not_block_but_app_descendant_still_does(self):
        browser = self.row(20, 1, '/apps/Google Chrome.app/Google Chrome')
        host = self.row(21, 20, self.identity['root'] + '/Contents/Helpers/chrome-native-host')
        harness = PlatformHarness('darwin', self.identity, [[browser, host]])
        with mock.patch.object(platform, 'app_identity', return_value=self.identity):
            self.assertFalse(platform.is_running('darwin', run=harness))
        owned = dict(host, parent=10)
        answer, commands = self.stop('darwin', [[self.row(), owned],
                                               [dict(owned, parent=1)], []])
        self.assertTrue(answer)
        self.assertEqual(sum(c[0] == '/bin/ps' for c in commands), 3)

    def test_reused_pid_after_quit_keeps_waiting_until_the_deadline(self):
        other = self.row(born='Mon Sep 28 10:00:01 2026', exe='/usr/bin/other')  # Same pid, new process.
        for name in ('darwin', 'win32', 'linux'):
            self.assertIs(self.stop(name, [[self.row()], [other]], timeout=0)[0], False, name)

    def test_seen_descendant_that_exits_as_a_zombie_counts_as_gone(self):
        main, child = self.row(), self.row(11, 10, '/tools/session-writer')
        for name, shown in (('darwin', '<defunct>'), ('linux', '-')):  # As ps shows it until reaped.
            zombie = dict(child, parent=1, state='Z', exe=shown)
            self.assertIs(self.stop(name, [[main, child], [zombie]], timeout=0)[0], True, name)

    def test_descendant_that_execs_is_waited_for_with_its_children(self):
        proc, tool = self.row(11, 10), self.row(12, 11, '/tools/git')  # Forked with Claude's executable.
        for name in ('darwin', 'win32', 'linux'):
            answer, commands = self.stop(name, [[proc], [dict(proc, exe='/bin/sh'), tool], [dict(tool, parent=1)], []])
            self.assertEqual((answer, len(commands)), (True, 5), name)  # Quit request, four probes.

    def test_failed_probe_after_quit_is_retried(self):
        for name in ('darwin', 'win32', 'linux'):
            snapshots = [[self.row()], OSError('probe failed'), subprocess.TimeoutExpired('ps', 5), []]
            self.assertIs(self.stop(name, snapshots)[0], True, name)

    def test_linux_unknown_executable_refuses_before_quit_prompt(self):
        for exe in ('-', self.identity['exe'] + ' (deleted)'):
            harness = PlatformHarness('linux', self.identity, [[self.row(exe=exe)]])
            with mock.patch.object(platform, 'app_identity', return_value=self.identity):
                with self.assertRaisesRegex(OSError, 'status is unknown'):
                    platform.request_stop('linux', run=harness)
            self.assertFalse(any(command[0] == 'zenity' for command in harness.commands))

    def test_unverified_claude_and_unknown_probe_refuse(self):
        for name in ('darwin', 'win32', 'linux'):
            with self.assertRaisesRegex(OSError, 'unverified'):
                self.stop(name, [[self.row(exe='/unknown/claude')]])
        with mock.patch.object(platform, 'app_identity', return_value=self.identity):
            with self.assertRaises(OSError):
                platform.is_running('darwin', run=lambda *a, **k: result('malformed process'))

    def test_windows_and_linux_unknown_effective_policy_refuse(self):
        for name in ('win32', 'linux'):
            with self.assertRaisesRegex(OSError, 'policy is unknown'):
                platform.policy_disabled(name)

    def test_selected_local_signin_restriction_blocks_switch(self):
        library = self.root / 'Claude-3p/configLibrary'
        library.mkdir(parents=True)
        entry = '11111111-2222-4333-8444-555555555555'
        (library / '_meta.json').write_text(json.dumps({'appliedId': entry}))
        (library / (entry + '.json')).write_text(json.dumps({
            'disableDeploymentModeChooser': True}))
        self.assertTrue(platform.policy_disabled('darwin', profile=library.parent))

    @unittest.skipIf(os.name == 'nt', 'macOS and Linux identity records a POSIX user ID')
    def test_native_identity_uses_bundle_and_desktop_entries(self):
        app = self.root / 'Claude.app'
        (app / 'Contents/MacOS').mkdir(parents=True)
        (app / 'Contents/MacOS/Claude').touch()
        info = dict(CFBundleIdentifier=platform.BUNDLE_ID, CFBundleExecutable='Claude')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        def locate(argv, **kwargs):
            self.assertEqual(argv[0], '/usr/bin/mdfind')
            self.assertIn(platform.BUNDLE_ID, argv[1])
            return result(str(app))
        identity = platform.app_identity('darwin', run=locate)
        self.assertEqual(identity['exe'], str(app / 'Contents/MacOS/Claude'))
        for paths in ('', str(app) + '\n/other/Claude.app'):
            with self.assertRaises(OSError):
                platform.app_identity('darwin', run=lambda *a, **k: result(paths))
        info['CFBundleIdentifier'] = 'untrusted.app'
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        with self.assertRaises(OSError):
            platform.app_identity('darwin', run=lambda *a, **k: result(str(app)))

    def test_dialog_windows_enums_and_wrapped_text_are_valid(self):
        for name in ('darwin', 'win32', 'linux'):
            run = mock.Mock(return_value=result('button returned:Continue'))
            self.assertTrue(platform.confirm('Open Claude?', name, run=run))
            blob = ' '.join(run.call_args.args[0])
            self.assertIn('SCG Router', blob)
            self.assertIn('Cancel', blob)
            self.assertIn(platform.ICON.name, blob)
        script = platform._windows_dialog("Task's long text", True)
        # Validate every assigned enum against the WinForms contract, not a token substring.
        enums = re.findall(
            r'\$\w+\.(AutoSizeMode|FlowDirection|DialogResult)=([^;]+);', script)
        allowed = {"'GrowAndShrink'", "'TopDown'", "'LeftToRight'", "'OK'", "'Cancel'"}
        self.assertEqual(len(enums), 5)
        self.assertTrue(all(value in allowed for _, value in enums))
        self.assertIn('$l.MaximumSize=New-Object System.Drawing.Size(440,0)', script)
        self.assertIn("Task''s long text", script)
        self.assertEqual(script.count('New-Object System.Windows.Forms.Button'), 2)

    def test_missing_dialog_and_failed_open_propagate(self):
        with self.assertRaises(FileNotFoundError):
            platform.confirm('Open Claude?', 'linux', run=mock.Mock(side_effect=FileNotFoundError()))
        with mock.patch.object(platform, 'app_identity', return_value=self.identity):
            for name in ('darwin', 'win32', 'linux'):
                with self.assertRaises(platform.subprocess.CalledProcessError):
                    platform.open_app(name, run=lambda *a, **k: result(returncode=1))

    @unittest.skipIf(os.name == 'nt', 'Windows forbids the quote this Linux path escapes')
    def test_linux_launcher_round_trips_desktop_argument_escaping_and_ownership(self):
        home = self.root / 'router ü " % $ ` \\ '
        home.mkdir()
        base = self.root / 'redirected-data'
        with mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(base)}):
            path = platform.install_launcher(home, '/python with space', action='start', platform_name='linux')
            text = path.read_text(encoding='utf-8')
            self.assertEqual(path.parent, base / 'applications')
            command = next(line[5:] for line in text.splitlines() if line.startswith('Exec='))
            # Desktop Entry unescape layer followed by its double-quoted Exec grammar.
            command = command.replace('\\\\', '\\')
            args = re.findall(r'"((?:\\.|[^"\\])*)"|([^ ]+)', command)
            decoded = [re.sub(r'\\([\\"`$])', r'\1', quoted).replace('%%', '%')
                       if quoted else plain for quoted, plain in args]
            self.assertEqual(decoded, ['/python with space', str(home / 'claude_profile_launch.py'), '--action', 'start'])
            platform.install_launcher(home, '/python with space', action='start', platform_name='linux')
            self.assertEqual(path.read_text(encoding='utf-8'), text)
            path.write_text('unowned', encoding='utf-8')
            with self.assertRaisesRegex(OSError, 'unowned'):
                platform.install_launcher(home, '/python', action='start', platform_name='linux')
            self.assertEqual(path.read_text(), 'unowned')

    def test_windows_shortcut_honors_redirected_appdata_and_owned_arguments(self):
        home = self.root / "router ü's space"
        home.mkdir()
        captured = {}

        def run(argv, **kwargs):
            script = argv[-1]
            self.assertEqual(argv[:3], ['powershell', '-NoProfile', '-Command'])
            # Strictly parse PowerShell single-quoted literals, including doubled quotes.
            values = re.findall(r"'(?:[^']|'')*'", script)
            decoded = [v[1:-1].replace("''", "'") for v in values]
            self.assertIn(str(home / 'claude_profile_launch.py'), ' '.join(decoded))
            self.assertIn('$s.Description -ne ', script)
            self.assertIn('$s.Arguments -ne ', script)
            self.assertIn('$s.Save()', script)
            captured['script'] = script
            return result()

        with mock.patch.dict(os.environ, {'APPDATA': str(self.root / 'roaming')}):
            path = platform.install_launcher(home, 'C:/Python/python.exe', run=run, platform_name='win32')
        self.assertEqual(path.parent, self.root / 'roaming/Microsoft/Windows/Start Menu/Programs')
        self.assertIn('--action switch', captured['script'])
        self.assertTrue((home / 'claude_profile_launch.py').is_file())

    def test_generated_powershell_parses_on_available_host_runtime(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            return  # The strict command harness above remains active on every host.
        _, commands = self.stop('win32', [[self.row()], []])
        scripts = [c[-1] for c in commands] + [platform._windows_dialog('Open Claude?', True)]
        def capture(argv, **kwargs):
            scripts.append(argv[-1])
            return result(json.dumps(self.identity))
        platform.app_identity('win32', run=capture)
        home = self.root / 'router'
        home.mkdir()
        platform.install_launcher(home, 'C:/Python/python.exe', applications=self.root / 'apps',
                                  run=capture, platform_name='win32')
        for script in scripts:
            encoded = base64.b64encode(script.encode('utf-8')).decode('ascii')
            check = "$tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseInput("
            check += "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s'))," % encoded
            check += '[ref]$tokens,[ref]$errors);if($errors.Count){exit 1}'
            answer = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-Command', check],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(answer.returncode, 0, answer.stderr)


if __name__ == '__main__':
    unittest.main()
