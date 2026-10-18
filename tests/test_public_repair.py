"""Public setup repairs owned clients without rekeying or changing saved choices."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import test_systemd as fixtures
from tests._platform import unix_only
from tests.install_fixtures import _craft_bundle, _static_fetch, install_mod
from tests.test_native_setup import module, resources


@unix_only
class PublicRepairTests(unittest.TestCase):
    def setUp(self):
        self.rig = fixtures.SystemdTests()
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)
        self.rig.install('1.2.6.174')
        self.home = self.rig.home
        self.key = self.home / 'openrouter.key'
        self.key.write_text('synthetic-working-key\n')
        self.key.chmod(0o600)
        self.state = install_mod.ensure_state(self.home)
        self.state.pop('setup', None)
        self.state.update(custom={'keep': True}, clients='codex', openai_mode='subscription')
        install_mod._write_state(self.home, self.state)
        (self.home / 'channel').write_text('beta\n')
        (self.home / 'download-auth.json').write_text('{legacy signed-out state')
        self.close = mock.Mock(return_value=True)
        patcher = mock.patch.object(install_mod._delivery, 'close_assistants', self.close)
        patcher.start()
        self.addCleanup(patcher.stop)

    def repair(self, version):
        blob, latest = _craft_bundle(version)
        args = install_mod.build_parser().parse_args(['--home', str(self.home),
            '--feed', 'file:///latest.json', '--python', sys.executable, '--repair'])
        with contextlib.redirect_stdout(io.StringIO()):
            return install_mod.do_install(args, _fetch=_static_fetch(latest, blob))

    def test_current_and_newer_repairs_keep_key_channel_and_harmless_client_drift(self):
        config = self.rig.root / 'user/.codex/config.toml'
        config.write_text(config.read_text().replace('openai_base_url =', 'openai_base_url  =')
                          + '\n# owner setting\n[features]\nkeep_disabled = false\n')
        for version in ('1.2.6.174', '1.3.2.185'):
            with self.subTest(version=version):
                self.assertEqual(self.repair(version), 0)
                state = install_mod.ensure_state(self.home)
                self.assertNotIn('setup', state)
                self.assertEqual(state['custom'], {'keep': True})
                self.assertEqual(state['clients'], 'codex')
                self.assertEqual(state['openai_mode'], 'subscription')
                self.assertEqual(self.key.read_text(), 'synthetic-working-key\n')
                self.assertEqual((self.home / 'channel').read_text(), 'beta\n')
                self.assertEqual((self.home / 'download-auth.json').read_text(), '{legacy signed-out state')
                self.assertIn('keep_disabled = false', config.read_text())
                self.assertEqual(install_mod.current_version(self.home), version)
        self.assertEqual(self.close.call_count, 2)

    def test_cancelled_interactive_repair_never_changes_client_settings(self):
        self.close.return_value = False
        config = self.rig.root / 'user/.codex/config.toml'
        before = config.read_bytes()
        with self.assertRaisesRegex(SystemExit, 'cancelled'):
            self.repair('1.3.2.185')
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(install_mod.current_version(self.home), '1.2.6.174')

    def test_only_verified_repair_clears_the_install_warning(self):
        self.state.update(last_error='installer_failed', installation_repair_required=True)
        install_mod._write_state(self.home, self.state)
        self.assertEqual(self.repair('1.2.6.174'), 0)
        after = install_mod.ensure_state(self.home)
        self.assertNotIn('installation_repair_required', after)
        self.assertNotIn('last_error', after)
        self.assertEqual(after['component_repairs']['assistants'], 'ready')
        config = self.rig.root / 'user/.codex/config.toml'
        config.write_text(config.read_text().replace('127.0.0.1', 'changed.example'))
        with self.assertRaises(SystemExit):
            self.repair('1.2.6.174')
        after = install_mod.ensure_state(self.home)
        self.assertTrue(after['installation_repair_required'])
        self.assertEqual(after['component_repairs']['assistants'], 'failed')

    def test_same_version_legacy_pointer_migrates_after_the_main_job_is_repaired(self):
        pointer = self.home / 'current'
        pointer.unlink()
        pointer.symlink_to(self.home / 'releases/1.2.6.174', target_is_directory=True)
        original = install_mod.wait_version
        with mock.patch.object(install_mod, 'wait_version', side_effect=lambda *a, **k:
                self.assertTrue(pointer.is_symlink()) or original(*a, **k)):
            self.assertEqual(self.repair('1.2.6.174'), 0)
        self.assertFalse(pointer.is_symlink())
        self.assertEqual(pointer.read_text().strip(), '1.2.6.174')


class NativeRepairArgumentsTests(unittest.TestCase):
    def test_native_repair_clears_controls_only_after_verified_shortcuts_are_installed(self):
        from tests.test_native_resources import NativeResourcesTests
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, _, _ = NativeResourcesTests().fixture(root)
            state = home / 'mixed-router-state.json'
            state.write_text(json.dumps(dict(component_repairs={'controls': 'failed', 'assistants': 'ready'},
                last_applied_version='1.3.0.9', last_error='installer_failed', installation_repair_required=True)))
            original, dialog, shortcuts = setup.load, mock.MagicMock(), mock.Mock()
            dialog.Progress.return_value.__enter__.return_value.cancelled = False
            shortcuts.install.side_effect = lambda home, permanent, python: (
                home / 'setup-current').write_text(permanent.name)
            modules = dict(native_dialog=dialog, native_shortcuts=shortcuts,
                           native_resources=owner, native_controller=mock.Mock(), desktop_menu=mock.Mock())
            with mock.patch.object(setup, 'load', side_effect=lambda name:
                    modules[name] if name in modules else original(name)), \
                    mock.patch.object(setup, 'run_installer', return_value=SimpleNamespace(returncode=0)), \
                    mock.patch.object(setup, '_select') as choose, \
                    mock.patch.object(setup, '_key'), mock.patch.object(setup, '_check'):
                self.assertEqual(setup.onboard(root / 'Resources', home, 'resume'), 0)
            choose.assert_not_called()
            self.assertEqual(shortcuts.install.call_count, 2)
            self.assertTrue(owner.ready(home))
            self.assertEqual(json.loads(state.read_text())['component_repairs']['controls'], 'ready')
            self.assertNotIn('installation_repair_required', json.loads(state.read_text()))
            self.assertNotIn('last_error', json.loads(state.read_text()))

    @unix_only
    def test_native_legacy_pointer_uses_repair_without_the_client_chooser(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            home = root / 'home'
            release = home / 'releases/1.2.6.174'
            release.mkdir(parents=True)
            (home / 'current').symlink_to(release, target_is_directory=True)
            original, dialog = setup.load, mock.MagicMock()
            with mock.patch.object(setup, 'load', side_effect=lambda name: dialog
                    if name in ('native_dialog', 'native_shortcuts') else original(name)), \
                    mock.patch.object(setup, 'retained', return_value=source), \
                    mock.patch.object(setup, '_select', return_value=['--clients', 'claude']) as choose, \
                    mock.patch.object(setup, 'run_installer', return_value=SimpleNamespace(returncode=1)) as run:
                self.assertEqual(setup.onboard(source, home, 'resume'), 1)
            choose.assert_not_called()
            self.assertEqual(run.call_args.args[-1], ['--repair'])

    def test_existing_setup_uses_public_saved_channel_and_newest_controller(self):
        payload = module('native_payload')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            (source / 'router/packaging/VERSION').write_text('1.2.0')
            home = root / 'home'
            home.mkdir()
            (home / 'channel').write_text('beta')
            control = home / 'control/1.3.2.185/packaging'
            control.mkdir(parents=True)
            (control / 'install.py').write_text('# verified retained controller')
            (home / 'control-version').write_text('1.3.2.185')
            args = payload.install_arguments(source, home, {'clients': 'claude'}, repair=True)
            self.assertEqual(args[1], str(control / 'install.py'))
            self.assertIn('https://dist.softwarecombined.com/beta/latest.json', args)
            self.assertIn('--repair', args)
            self.assertNotIn('--clients', args)
            self.assertNotIn('--setup', args)
            self.assertNotIn('--choose-clients', args)

    def test_stable_controls_run_newer_maintenance_code_after_runtime_rollback(self):
        root_source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            source = resources(home / 'setup/old', version='1.2.0')
            (home / 'setup-current').write_text('old')
            (home / 'current').write_text('1.2.6.174')
            (home / 'control-version').write_text('1.3.2.185')
            control = home / 'control/1.3.2.185/packaging'
            control.mkdir(parents=True)
            for name in ('native_setup.py', 'desktop_menu.py'):
                (control / name).write_text('import json,sys\nprint(json.dumps(dict(new=True,args=sys.argv)))\n')
                (source / 'router/packaging' / name).write_text("raise SystemExit('old controls ran')\n")
            for launcher, flags in (('native_launch.py', ['--status']), ('desktop_launch.py', [])):
                (home / launcher).write_bytes((root_source / 'packaging' / launcher).read_bytes())
                done = subprocess.run([sys.executable, str(home / launcher), *flags],
                                      capture_output=True, text=True, timeout=15)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertTrue(json.loads(done.stdout)['new'])


class RepairCloseTests(unittest.TestCase):
    def owner(self, answer=True, running=True, stopped=True):
        owner = module('repair_ui')
        receipts, dialog, platform = mock.Mock(), mock.Mock(), mock.Mock()
        receipts.read_receipt.return_value = {'clients': {'codex': {}}}
        dialog.confirm_result.return_value = answer
        platform.is_running.return_value = running
        platform.request_stop.return_value = stopped
        codex = SimpleNamespace(CODEX=SimpleNamespace(bundle_id='com.openai.codex'))
        owner._load = lambda name: {'codex_config': receipts, 'native_dialog': dialog,
            'claude_desktop_platform': platform, 'codex_desktop_switch': codex}[name]
        return owner, dialog, platform

    def test_cancel_or_missing_dialog_never_closes_an_assistant(self):
        for answer in (False, None):
            owner, _, platform = self.owner(answer=answer)
            self.assertFalse(owner.close_assistants(Path('/synthetic/home')))
            platform.request_stop.assert_not_called()

    def test_repair_stops_only_through_graceful_owner_and_refuses_a_failed_close(self):
        owner, dialog, platform = self.owner(stopped=False)
        self.assertFalse(owner.close_assistants(Path('/synthetic/home')))
        platform.request_stop.assert_called_once()
        self.assertIn('Codex', dialog.confirm_result.call_args.args[0])
        self.assertNotIn('Claude', dialog.confirm_result.call_args.args[0])

    def test_unknown_app_identity_requires_manual_close_confirmation(self):
        owner, dialog, platform = self.owner()
        platform.is_running.side_effect = OSError('unknown app')
        dialog.confirm_result.side_effect = [True, False]
        self.assertFalse(owner.close_assistants(Path('/synthetic/home')))
        self.assertEqual(dialog.confirm_result.call_count, 2)
        platform.request_stop.assert_not_called()
