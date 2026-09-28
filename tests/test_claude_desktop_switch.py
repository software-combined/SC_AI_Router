"""Offline Claude switching: user cancellation and profile preservation."""
import importlib.util
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_claude_desktop_config import _profile, _state, desktop_config
from tests.install_fixtures import install_mod

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'desktop_switch', ROOT / 'packaging' / 'claude_desktop_switch.py')
switcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switcher)


def result(stdout='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)


class SwitchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'router'
        self.home.mkdir()
        (self.home / '.claude-profile-switch.lock').touch(mode=0o600)
        self.profile = _profile(self.root, {'keep': 'gateway setting'})
        self.state = _state()
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
        desktop_config.attach(self.home, self.state, install_mod._codex_config,
                              data_dir_override=self.profile)
        self.config = self.profile / 'claude_desktop_config.json'
        self.config.write_text(json.dumps({'deploymentMode': '3p', 'keep': {'nested': True}}))
        install_mod._codex_config.write_client_receipt(self.home, 'codex', {'keep': 'receipt'})
        native = self.root / 'Claude'
        native.mkdir()
        (native / 'conversations').write_text('native session sentinel')
        (self.profile / 'conversations').write_text('gateway session sentinel')
        self.sync = mock.Mock(return_value={
            'copied': 0, 'replaced': 0, 'unchanged': 0,
            'pending': 0, 'failed': 0, 'errors': []})
        self.profile_env = {'CLAUDE_FIRST_PARTY_DATA_DIR': str(native)}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(switcher.sys, 'platform', 'darwin').start()
        mock.patch.object(switcher, '_initialized', return_value=True).start()
        mock.patch.object(switcher._platform, 'is_running', return_value=False).start()
        mock.patch.object(switcher._platform, 'request_stop', side_effect=lambda *_a, **_k:
                          self.run(['quit'], timeout=65).stdout == 'stopped').start()
        mock.patch.object(switcher._platform, 'open_app', side_effect=lambda *_a, **_k:
                          self.run(['/usr/bin/open', '-b', switcher.BUNDLE_ID])).start()
        self.run = mock.Mock(side_effect=[result('button returned:Continue'),
                                          result('stopped'), result()])
        self.policy = mock.Mock(return_value=False)

    def files(self):
        return {p.relative_to(self.root): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def switch(self):
        return switcher.switch(
            self.home, run=self.run, policy_check=self.policy,
            sync=self.sync, profile_env=self.profile_env)

    def test_round_trip_changes_only_mode_and_preserves_receipts_and_sessions(self):
        before = self.files()
        for expected in ('1p', '3p'):
            with self.subTest(expected=expected):
                self.run.side_effect = [result('button returned:Continue'), result('stopped'), result()]
                self.assertEqual(self.switch(), expected)
                self.assertEqual(json.loads(self.config.read_text()),
                                 {'deploymentMode': expected, 'keep': {'nested': True}})
                after = self.files()
                for path, data in before.items():
                    if path != self.config.relative_to(self.root):
                        self.assertEqual(after[path], data, str(path))
                self.assertEqual(self.run.call_args.args[0],
                                 ['/usr/bin/open', '-b', switcher.BUNDLE_ID])

    def test_cancel_quit_failure_and_timeout_never_write_or_reopen(self):
        cases = ([result(returncode=1)],
                 [result('button returned:Continue'), result(returncode=1)],
                 [result('button returned:Continue'), result('running')],
                 [result('button returned:Continue'), subprocess.TimeoutExpired('osascript', 65)])
        for answers in cases:
            with self.subTest(answers=answers):
                before = self.files()
                self.run.reset_mock(side_effect=True)
                self.run.side_effect = answers
                if len(answers) == 1:
                    self.assertIsNone(self.switch())
                else:
                    with self.assertRaises(switcher.SwitchError):
                        self.switch()
                self.assertEqual(self.files(), before)
                self.assertFalse(any(c.args[0][0] == '/usr/bin/open' for c in self.run.call_args_list))

    def test_unrelated_setting_written_during_quit_is_retained(self):
        def run(argv, **kwargs):
            if argv[0] == '/usr/bin/open':
                return result()
            if 'display dialog' in argv[-1]:
                return result('button returned:Continue')
            doc = json.loads(self.config.read_text())
            doc['writtenOnExit'] = 42
            self.config.write_text(json.dumps(doc))
            return result('stopped')
        self.run.side_effect = run
        self.assertEqual(self.switch(), '1p')
        self.assertEqual(json.loads(self.config.read_text())['writtenOnExit'], 42)

    def test_main_reports_sanitized_errors_through_the_platform_dialog(self):
        with mock.patch.object(
                switcher, 'switch',
                side_effect=switcher.SwitchError('Try again.')):
            with mock.patch.object(switcher._platform, 'show_message') as show:
                self.assertEqual(
                    switcher.main(['--home', str(self.home)]), 1)
        show.assert_called_once_with('Try again.', switcher.sys.platform)

    def test_unexpected_errors_do_not_reveal_private_exception_text(self):
        with mock.patch.object(switcher, 'switch', side_effect=RuntimeError('private profile detail')), \
                mock.patch.object(switcher._platform, 'show_message') as show, \
                mock.patch('sys.stderr') as stderr:
            self.assertEqual(switcher.main(['--home', str(self.home)]), 1)
        self.assertNotIn('private profile detail', str(show.call_args) + str(stderr.mock_calls))

    def test_unknown_policy_or_writer_status_refuses_before_sync(self):
        for unknown in ('policy', 'writer'):
            with self.subTest(unknown=unknown):
                self.policy.return_value = None if unknown == 'policy' else False
                before = self.files()
                with mock.patch.object(switcher._platform, 'is_running', return_value=None):
                    with self.assertRaises(switcher.SwitchError):
                        self.switch()
                self.sync.assert_not_called()
                self.assertEqual(before, self.files())

    def test_malformed_completion_report_cannot_change_mode(self):
        self.sync.return_value = {}
        before = self.files()
        with self.assertRaisesRegex(switcher.SwitchError, 'not fully shared'):
            self.switch()
        self.assertEqual(before, self.files())

    def test_real_policy_reader_rechecks_local_restriction_after_quit(self):
        library = self.profile / 'configLibrary'
        entry = library / '11111111-2222-4333-8444-555555555555.json'
        before = self.config.read_bytes()

        def stop(*args, **kwargs):
            doc = json.loads(entry.read_text())
            doc['disableDeploymentModeChooser'] = True
            entry.write_text(json.dumps(doc))
            return True

        with mock.patch.object(switcher._platform._policy, 'managed_macos', return_value={}), \
                mock.patch.object(switcher._platform, 'request_stop', side_effect=stop):
            with self.assertRaisesRegex(switcher.SwitchError, 'organization manages'):
                switcher.switch(self.home, run=self.run, sync=self.sync,
                                profile_env=self.profile_env)
        self.sync.assert_not_called()
        switcher._platform.open_app.assert_not_called()
        self.assertEqual(self.config.read_bytes(), before)

    def test_policy_changed_during_copy_prevents_mode_write_and_reopen(self):
        self.policy.side_effect = [False, False, True]
        before = self.files()
        with self.assertRaisesRegex(switcher.SwitchError, 'organization manages'):
            self.switch()
        self.sync.assert_called_once()
        self.assertEqual(self.files(), before)
        switcher._platform.open_app.assert_not_called()

    def test_reopened_or_unknown_app_after_copy_prevents_mode_write_and_reopen(self):
        for status in (True, None, OSError('status unavailable')):
            with self.subTest(status=status):
                self.run.side_effect = [result('button returned:Continue'), result('stopped'), result()]
                before = self.files()
                with mock.patch.object(switcher._platform, 'is_running',
                                       side_effect=[False, status]):
                    with self.assertRaises(switcher.SwitchError):
                        self.switch()
                self.assertEqual(self.files(), before)
                switcher._platform.open_app.assert_not_called()

    def test_parallel_open_and_switch_refuse_through_sync_and_reopen(self):
        other = mock.Mock()
        other.confirm.return_value = other.request_stop.return_value = True
        other.is_running.return_value = False
        other.open_app.return_value = result()
        other_sync = mock.Mock(return_value=self.sync.return_value)

        def attempt_parallel_actions():
            for action in ('switch', 'start'):
                with self.assertRaisesRegex(switcher.SwitchError, 'already'):
                    switcher.switch(
                        self.home, policy_check=lambda: False, action=action,
                        platform_ops=other, sync=other_sync,
                        profile_env=self.profile_env)
            self.assertEqual(other.mock_calls, [])
            other_sync.assert_not_called()

        def sync(*args):
            attempt_parallel_actions()
            return self.sync.return_value

        def reopen(*args, **kwargs):
            attempt_parallel_actions()
            return result()

        self.sync.side_effect = sync
        with mock.patch.object(switcher._platform, 'open_app', side_effect=reopen):
            self.assertEqual(self.switch(), '1p')
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '1p')
        self.sync.assert_called_once()

    def test_old_release_is_rejected_before_dispatch(self):
        launcher = switcher._load('claude_profile_launch')
        (self.home / 'current').write_text('old', encoding='utf-8')
        helper = self.home / 'releases/old/packaging/claude_desktop_switch.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('def main(): raise RuntimeError("must not run")', encoding='utf-8')
        with mock.patch.object(launcher.runpy, 'run_path') as run:
            with self.assertRaisesRegex(SystemExit, 'Update SCG Router'):
                launcher.main(['--home', str(self.home), '--action', 'start'])
        run.assert_not_called()

    def test_changed_attachment_after_quit_is_not_overwritten(self):
        def run(argv, **kwargs):
            if 'display dialog' in argv[-1]:
                return result('button returned:Continue')
            self.config.write_text('{"deploymentMode":"1p","changed":true}')
            return result('stopped')
        self.run.side_effect = run
        with self.assertRaisesRegex(switcher.SwitchError, 'settings changed'):
            self.switch()
        self.assertEqual(json.loads(self.config.read_text()),
                         {'deploymentMode': '1p', 'changed': True})
        self.assertEqual(self.run.call_count, 2)

    def test_missing_or_changed_gateway_refuses_before_quit(self):
        receipt = self.home / 'activation.json'
        saved = receipt.read_bytes()
        for damage in ('receipt', 'gateway'):
            with self.subTest(damage=damage):
                receipt.write_bytes(saved)
                if damage == 'receipt':
                    receipt.unlink()
                else:
                    entry = self.profile / 'configLibrary' / '11111111-2222-4333-8444-555555555555.json'
                    entry.write_text('{"inferenceProvider":"another"}')
                before = self.files()
                with self.assertRaisesRegex(switcher.SwitchError, 'Run setup again'):
                    self.switch()
                self.run.assert_not_called()
                self.assertEqual(self.files(), before)

    def test_managed_chooser_restriction_prevents_changes(self):
        self.policy.return_value = True
        before = self.files()
        with self.assertRaisesRegex(switcher.SwitchError, 'organization manages'):
            self.switch()
        self.run.assert_not_called()
        self.assertEqual(self.files(), before)

    def test_failed_reopen_keeps_chosen_mode_and_explains_next_action(self):
        self.run.side_effect = [result('button returned:Continue'), result('stopped'),
                               subprocess.CalledProcessError(1, 'open')]
        with self.assertRaisesRegex(switcher.SwitchError, 'Open Claude to continue'):
            self.switch()
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '1p')

    def test_prompt_names_destination_and_has_safe_action_and_product_icon(self):
        for mode, label in switcher.DESTINATIONS.items():
            with self.subTest(mode=mode):
                self.config.write_text(json.dumps({'deploymentMode': '3p' if mode == '1p' else '1p'}))
                self.run.side_effect = [result(returncode=1)]
                self.switch()
                script = self.run.call_args.args[0][-1]
                self.assertIn(label, script)
                self.assertIn('"SCG Router"', script)
                self.assertIn('buttons {"Cancel", "Continue"}', script)
                self.assertIn(str(switcher.ICON), script)
                for word in ('nonce', 'loopback', 'catalogue', 'token', 'endpoint', 'process'):
                    self.assertNotIn(word, script.lower())

    def test_installed_launcher_uses_stable_entrypoint_and_owned_icon(self):
        (self.home / 'current').write_text('new')
        helper = self.home / 'releases/new/packaging/claude_desktop_switch.py'
        helper.parent.mkdir(parents=True)
        helper.write_text("PROFILE_ACTIONS = ('start', 'switch')")
        helper.with_name('claude_profile_sync.py').touch()
        self.run.side_effect = None
        self.run.return_value = result()
        app = switcher.install_launcher(self.home, '/python path/python3',
                                        applications=self.root / 'Applications', run=self.run)
        info = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
        self.assertEqual(info['CFBundleIdentifier'], switcher.LAUNCHER_ID)
        self.assertEqual(info['CFBundleName'], 'Switch Claude')
        self.assertEqual(info['CFBundleIconFile'], 'router.icns')
        executable = app / 'Contents' / 'MacOS' / info['CFBundleExecutable']
        self.assertIn("'/python path/python3'", executable.read_text())
        self.assertIn('claude_profile_launch.py', executable.read_text())
        self.assertNotIn('/releases/', executable.read_text())
        self.assertTrue(executable.stat().st_mode & 0o100)
        self.assertEqual((self.home / 'claude_profile_launch.py').read_bytes(),
                         (ROOT / 'packaging' / 'claude_profile_launch.py').read_bytes())
        self.assertEqual(self.run.call_args_list[0].args[0][4], str(switcher.ICON))

    def test_launcher_follows_current_release_after_update(self):
        spec = importlib.util.spec_from_file_location(
            'switch_launch', ROOT / 'packaging' / 'claude_profile_launch.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        launch_path = self.home / 'claude_profile_launch.py'
        for version in ('first', 'updated'):
            with self.subTest(version=version):
                (self.home / 'current').write_text(version)
                helper = self.home / 'releases' / version / 'packaging' / 'claude_desktop_switch.py'
                helper.parent.mkdir(parents=True)
                helper.write_text("PROFILE_ACTIONS = ('start', 'switch')")
                helper.with_name('claude_profile_sync.py').touch()
                with mock.patch.object(launcher, '__file__', str(launch_path)), \
                     mock.patch.object(launcher.runpy, 'run_path') as run, \
                     mock.patch.object(launcher.sys, 'argv', []):
                    launcher.main()
                    run.assert_called_once_with(str(helper), run_name='__main__')
                    self.assertEqual(launcher.sys.argv, [
                        str(helper), '--home', str(self.home),
                        '--action', 'switch'])


if __name__ == '__main__':
    unittest.main()
