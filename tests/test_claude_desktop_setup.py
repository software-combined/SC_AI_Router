"""Desktop attachment works without a new router release or manual setup."""
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod
from tests._platform import unix_only
from tests.test_install_lifecycle import _run_install


class DesktopSetupTests(unittest.TestCase):
    def setUp(self):
        fake_home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ,
                          {'HOME': fake_home, 'USERPROFILE': fake_home}))
        self.enterContext(mock.patch.object(install_mod._svc, 'wait_version', return_value=True))
        self.enterContext(mock.patch.object(install_mod._svc, 'channel_feed',
                                           return_value='file:///latest.json'))
        self.enterContext(mock.patch.object(install_mod, 'platform_backend'))
        self.real_install_launcher = install_mod._desktop_config._install_switch_launcher
        launcher = mock.patch.object(install_mod._desktop_config, '_install_switch_launcher')
        self.launcher = launcher.start()
        self.addCleanup(launcher.stop)

    def test_changed_default_preserves_the_original_attachment_until_explicit_detach(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, old, new = (Path(tmp) / name for name in ('router', 'roaming', 'local'))
            home.mkdir()
            desktop, receipts = install_mod._desktop_config, install_mod._codex_config
            state = {'port': 1, 'token': 'test-token'}
            entry = desktop.attach(home, state, receipts, data_dir_override=old)
            before = {p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
            with mock.patch.object(desktop, 'user_data_dir', return_value=new):
                with self.assertRaisesRegex(SystemExit, 'different profile'):
                    desktop.attach(home, state, receipts)
                self.assertFalse(new.exists())
                self.assertEqual({p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}, before)
                self.assertEqual(desktop.attach(home, state, receipts, data_dir_override=old), entry)
                self.assertEqual({p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}, before)

    def test_repeat_attachment_preserves_subscription_choice_and_original_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            profile = Path(tmp) / 'Claude-3p'
            profile.mkdir()
            config = profile / 'claude_desktop_config.json'
            config.write_text('{"keep":"original"}')
            desktop, receipts = install_mod._desktop_config, install_mod._codex_config
            state = {'port': 1, 'token': 'test-token'}
            desktop.attach(home, state, receipts, data_dir_override=profile)
            before = (home / 'activation.json').read_bytes()
            config.write_text('{"deploymentMode":"1p","keep":"original"}')
            for _ in range(2):
                desktop.attach(home, state, receipts, data_dir_override=profile)
                self.assertEqual(json.loads(config.read_text()),
                                 {'deploymentMode': '1p', 'keep': 'original'})
                self.assertEqual((home / 'activation.json').read_bytes(), before)
            desktop.detach(home, receipts)
            # A subscription choice made after attachment belongs to the user.
            self.assertEqual(json.loads(config.read_text()),
                             {'deploymentMode': '1p', 'keep': 'original'})

    def test_receipt_for_another_entry_does_not_claim_subscription_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, profile = Path(tmp) / 'router', Path(tmp) / 'Claude-3p'
            home.mkdir()
            desktop, receipts = install_mod._desktop_config, install_mod._codex_config
            state = {'port': 1, 'token': 'test-token'}
            entry = desktop.attach(home, state, receipts, data_dir_override=profile)
            other = entry.with_name('another.json')
            other.write_bytes(entry.read_bytes())
            meta = entry.parent / '_meta.json'
            meta.write_text('{"appliedId":"another","entries":[]}')
            config = profile / 'claude_desktop_config.json'
            config.write_text('{"deploymentMode":"1p"}')
            before = {p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
            with self.assertRaisesRegex(SystemExit, 'managed outside'):
                desktop.attach(home, state, receipts, data_dir_override=profile)
            self.assertEqual({p: p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}, before)

    def test_current_install_attaches_desktop_without_reinstalling(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            (home / 'releases/1.0.0').mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            state = {'port': 1, 'token': 'test-token', 'claude_mode': 'subscription'}
            (home / 'mixed-router-state.json').write_text(json.dumps(state))
            profile = Path(tmp) / 'Claude-3p'
            args = install_mod.build_parser().parse_args([
                '--home', str(home), '--feed', 'file:///latest.json', '--desktop'])
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                    mock.patch.object(install_mod, 'install_bundle') as bundle, \
                    contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
            bundle.assert_not_called()
            self.assertEqual((home / 'current').read_text(), '1.0.0')
            entry = install_mod._desktop_config.applied_entry_path(profile)
            self.assertEqual(json.loads(entry.read_text())['inferenceProvider'], 'gateway')
            self.assertIn('claude-desktop', install_mod._codex_config.read_receipt(home)['clients'])

    def test_current_desktop_dry_run_does_not_create_a_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            (home / 'releases/1.0.0').mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            profile = Path(tmp) / 'Claude-3p'
            args = install_mod.build_parser().parse_args([
                '--home', str(home), '--feed', 'file:///latest.json', '--desktop', '--dry-run'])
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                    contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
            self.assertFalse(profile.exists())
            self.assertFalse((home / 'activation.json').exists())

    def test_current_attachment_installs_launcher_without_standalone_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, profile = Path(tmp) / 'router', Path(tmp) / 'Claude-3p'
            home.mkdir()
            (home / 'releases/1.0.0').mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            (home / 'mixed-router-state.json').write_text('{"port":1,"token":"test-token"}')
            desktop, receipts = install_mod._desktop_config, install_mod._codex_config
            args = install_mod.build_parser().parse_args(['--home', str(home), '--desktop'])
            calls = []

            def installed(target, python, env=None):
                self.assertIn('claude-desktop', receipts.read_receipt(target)['clients'])
                self.assertEqual(desktop.read_entry(desktop.applied_entry_path(profile))
                                 ['inferenceProvider'], 'gateway')
                calls.append((target, python))

            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch('shutil.which', return_value=None), \
                    mock.patch.object(install_mod, 'find_python', return_value='/python3.14'), \
                    mock.patch.object(desktop, '_install_switch_launcher', side_effect=installed), \
                    contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
            self.assertEqual(calls, [(home, '/python3.14')])

    def test_launcher_failures_name_the_action_and_keep_installing(self):
        desktop = install_mod._desktop_config
        calls = []

        class FakeSwitchError(Exception):
            pass

        def exec_module(module):
            module.SwitchError = FakeSwitchError
            module.subprocess = SimpleNamespace(
                SubprocessError=subprocess.SubprocessError)

            def install(_home, _python, action):
                calls.append(action)
                if action == 'start':
                    raise FakeSwitchError('already exists')
            module.install_launcher = install
            module._load = lambda _name: SimpleNamespace(install=lambda *args: None)

        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=exec_module))
        output = io.StringIO()
        with mock.patch.object(desktop.sys, 'platform', 'darwin'), \
                mock.patch.object(desktop._ilu, 'spec_from_file_location',
                                  return_value=spec), \
                mock.patch.object(desktop._ilu, 'module_from_spec',
                                  return_value=SimpleNamespace()), \
                contextlib.redirect_stdout(output):
            self.real_install_launcher('/router', '/python')
        self.assertEqual(calls, ['switch', 'start'])
        self.assertIn('Open Claude could not be installed', output.getvalue())
        self.assertNotIn('Switch Claude could not be installed', output.getvalue())

    @unix_only
    def test_upgrade_refreshes_existing_desktop_shortcut_and_keeps_subscription_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, profile = Path(tmp) / 'router', Path(tmp) / 'Claude-3p'
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(_run_install(self, tmp, home, '1.0.0', '--desktop')[0], 0)
                receipt = install_mod._codex_config.read_receipt(home)['clients']['claude-desktop']
                config = profile / 'claude_desktop_config.json'
                config.write_text('{"deploymentMode":"1p","keep":"native choice"}')
                self.launcher.reset_mock()
                self.assertEqual(_run_install(self, tmp, home, '1.0.1')[0], 0)
            self.assertEqual(json.loads(config.read_text()),
                             {'deploymentMode': '1p', 'keep': 'native choice'})
            self.assertEqual(install_mod._codex_config.read_receipt(home)
                             ['clients']['claude-desktop'], receipt)
            self.launcher.assert_called_once_with(home, '/opt/homebrew/bin/python3.14', None)

    def test_dry_run_with_launcher_interpreter_does_not_write_or_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            args = install_mod.build_parser().parse_args([
                '--home', str(home), '--desktop', '--dry-run'])
            desktop = install_mod._desktop_config
            with mock.patch.object(desktop, '_install_switch_launcher') as launcher, \
                    contextlib.redirect_stdout(io.StringIO()):
                desktop.attach_current(args, install_mod._codex_config,
                                       install_mod._write_state, python='/python3.14')
            launcher.assert_not_called()
            self.assertFalse(home.exists())

    @unix_only
    def test_older_current_release_connects_without_creating_a_dead_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, profile = root / 'router', root / 'Claude-3p'
            (home / 'releases/0.6.99/packaging').mkdir(parents=True)
            (home / 'current').write_text('0.6.99')
            (home / 'mixed-router-state.json').write_text('{"port":1,"token":"test-token"}')
            args = install_mod.build_parser().parse_args(['--home', str(home), '--desktop'])
            output = io.StringIO()
            with mock.patch.dict(os.environ, {'HOME': str(root), 'USERPROFILE': str(root),
                                             'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch('sys.platform', 'darwin'), \
                    mock.patch.object(install_mod, 'find_python', return_value='/python3.14'), \
                    mock.patch.object(install_mod._desktop_config, '_install_switch_launcher',
                                      side_effect=self.real_install_launcher), \
                    mock.patch('subprocess.run'), contextlib.redirect_stdout(output):
                self.assertEqual(install_mod.do_install(args,
                                 _fetch=lambda _: b'{"version":"0.6.99"}'), 0)
            self.assertFalse((root / 'Applications/Switch Claude.app').exists())
            self.assertIn('Update SCG Router', output.getvalue())
            self.assertIn('claude-desktop', install_mod._codex_config.read_receipt(home)['clients'])
            self.assertEqual((home / 'current').read_text(), '0.6.99')

    def test_corrupt_library_metadata_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'Claude-3p'
            library = profile / 'configLibrary'
            library.mkdir(parents=True)
            meta = library / '_meta.json'
            meta.write_text('broken')
            state = {'port': 1, 'token': 'test-token'}
            with self.assertRaisesRegex(SystemExit, 'library metadata'):
                install_mod._desktop_config.attach(Path(tmp), state,
                    install_mod._codex_config, data_dir_override=profile)
            self.assertEqual(meta.read_text(), 'broken')

    def test_current_install_applies_explicit_claude_mode(self):
        for previous, selected in (('none', 'subscription'), ('subscription', 'none')):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                (home / 'releases/1.0.0').mkdir(parents=True)
                (home / 'current').write_text('1.0.0')
                state = {'port': 1, 'token': 'test-token', 'claude_mode': previous}
                settings = home / 'mixed-router-state.json'
                settings.write_text(json.dumps(state))
                profile = Path(tmp) / 'Claude-3p'
                args = install_mod.build_parser().parse_args([
                    '--home', str(home), '--desktop', '--claude-mode', selected])
                with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                        mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if selected == 'none':
                        with self.assertRaisesRegex(SystemExit, 'claude_mode is none'):
                            install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
                        self.assertFalse(profile.exists())
                    else:
                        install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
                        self.assertTrue(profile.exists())
                self.assertEqual(json.loads(settings.read_text())['claude_mode'], selected)

    def test_failed_initial_metadata_write_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            profile = Path(tmp) / 'Claude-3p'
            desktop = install_mod._desktop_config
            state = {'port': 1, 'token': 'test-token'}
            write = desktop.write_json

            def fail_metadata(path, doc):
                if Path(path).name == '_meta.json':
                    raise OSError('synthetic write failure')
                write(path, doc)

            with mock.patch.object(desktop, 'write_json', side_effect=fail_metadata):
                with self.assertRaises(OSError):
                    desktop.attach(home, state, install_mod._codex_config,
                                   data_dir_override=profile)
            entry = desktop.attach(home, state, install_mod._codex_config,
                                   data_dir_override=profile)
            self.assertEqual(desktop.read_entry(entry)['inferenceProvider'], 'gateway')


if __name__ == '__main__':
    unittest.main()
