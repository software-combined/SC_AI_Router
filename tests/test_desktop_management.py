"""Management controls report owner outcomes and cannot reopen during a transition."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import test_codex_desktop_switch as codex_fixtures
from tests.test_native_setup import module, resources


class DesktopManagementTests(unittest.TestCase):
    def test_windows_and_linux_desktop_setup_keep_the_account_identity_callback(self):
        desktop = module('claude_desktop_config')
        for platform in ('win32', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                home = root / 'router'
                home.mkdir()
                settings = root / 'claude'
                with mock.patch.object(desktop.sys, 'platform', platform):
                    desktop._install_switch_launcher(home, sys.executable,
                        {'CLAUDE_CONFIG_DIR': str(settings)})
                self.assertTrue((home / 'claude_profile_launch.py').is_file())
                self.assertTrue((home / 'claude-profile-hook-receipt.json').is_file())
                hook = json.loads((settings / 'settings.json').read_bytes())['hooks']['SessionStart'][0]
                self.assertIn('capture', hook['hooks'][0]['command'])
                self.assertTrue(hook['hooks'][0]['async'])

    def test_update_starts_the_menu_silently_and_preserves_startup_opt_out(self):
        menu = module('desktop_menu')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'desktop_launch.py').write_text('# stable launcher')
            (home / 'control').mkdir()
            (home / 'control' / ('scg-router-menu.exe' if os.name == 'nt'
                                else 'scg-router-menu')).touch()
            with mock.patch.object(menu.subprocess, 'Popen') as launch:
                menu.start(home, home, autostart=True)
                self.assertEqual(launch.call_args.args[0][-1], '--autostart')
                launch.reset_mock()
                (home / 'desktop-preferences.json').write_text('{"autostart":false}')
                menu.start(home, home, autostart=True)
                launch.assert_not_called()

    def test_selecting_openrouter_only_is_a_noop_for_an_install_without_a_subscription(self):
        case = codex_fixtures.SwitchFlowTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.attach('none')
        before = (case.config.read_bytes(), (case.home / 'activation.json').read_bytes())
        app = case.fake()
        self.assertEqual(codex_fixtures.switcher.switch(case.home, target='switched',
                         platform_ops=app), 'switched')
        self.assertEqual(app.calls, [])
        self.assertEqual((case.config.read_bytes(), (case.home / 'activation.json').read_bytes()), before)

    def test_deferred_removal_never_reports_success(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home = resources(root / 'Resources'), root / 'home'
            home.mkdir()
            dialog = mock.Mock()
            controller = SimpleNamespace(launcher_source=lambda home, source: source)
            with mock.patch.object(setup, 'load', side_effect=lambda name:
                    controller if name == 'native_controller' else dialog), \
                    mock.patch.object(setup.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout=b'deferred: another router operation is in progress\n')):
                self.assertNotEqual(setup.onboard(source, home, 'remove'), 0)
            self.assertNotIn('SCG Router was removed.', [call.args[0] for call in dialog.message.call_args_list])

    def test_deferred_key_repair_never_opens_a_key_window(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home = resources(root / 'Resources'), root / 'home'
            home.mkdir()
            (home / 'mixed-router-state.json').write_text('{}')
            run = mock.Mock()
            with mock.patch.object(setup, 'run_installer', return_value=SimpleNamespace(
                    returncode=0, stdout='deferred: another router operation is in progress\n')):
                with self.assertRaises(ValueError):
                    setup._key(source, home, replace=True, run=run)
            run.assert_not_called()

    def test_open_codex_waits_for_the_installation_and_transition_owner(self):
        control, service = module('desktop_control'), module('service')
        owner = mock.Mock()
        modules = dict(native_dialog=mock.Mock(), codex_desktop_switch=owner, service=service)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with service.install_lock(home), mock.patch.object(control, 'load', side_effect=modules.__getitem__):
                with self.assertRaisesRegex(RuntimeError, 'operation is in progress'):
                    control.execute(home, home, 'codex.open')
            owner._platform.open_app.assert_not_called()

    def test_support_reveals_only_the_redacted_bundle_written_by_the_owner(self):
        control = module('desktop_control')
        for platform in ('darwin', 'win32', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary).resolve()
                (home / 'logs').mkdir()
                bundle = home / 'logs/support-20261018T000000Z.json'
                bundle.write_text('{}')
                command = (['open', '-R', str(bundle)] if platform == 'darwin' else
                           ['explorer', '/select,', str(bundle)] if platform == 'win32' else
                           ['xdg-open', str(bundle.parent)])
                run = mock.Mock()
                with mock.patch.object(control, '_installer', return_value=SimpleNamespace(
                        returncode=0, stdout=str(bundle) + '\n')), \
                        mock.patch.object(control, 'load', return_value=mock.Mock()), \
                        mock.patch.object(control.sys, 'platform', platform):
                    self.assertEqual(control.execute(home, home, 'help.support', run)['outcome'], 'done')
                self.assertEqual(run.call_args.args[0], command)

    def test_support_never_reveals_a_path_outside_the_owned_support_folder(self):
        control = module('desktop_control')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            path = home / 'unrelated.json'
            path.write_text('{}')
            run = mock.Mock()
            with mock.patch.object(control, '_installer', return_value=SimpleNamespace(
                    returncode=0, stdout=str(path))), mock.patch.object(control, 'load', return_value=mock.Mock()):
                with self.assertRaises(ValueError):
                    control.execute(home, home, 'help.support', run)
            run.assert_not_called()

    def test_menu_delivery_failure_is_distinct_from_running_router_health(self):
        control = module('desktop_control')
        installer = mock.Mock()
        installer._diag._status_document.return_value = dict(
            serving=True, routing_healthy=True, version='1.3.0.9', clients={})
        modules = dict(install=installer, update_status=module('update_status'),
                       desktop_startup=SimpleNamespace(enabled=lambda _: True))
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'desktop-delivery.json').write_text('{"status":"failed","private":"secret"}')
            with mock.patch.object(control, 'load', side_effect=modules.__getitem__):
                facts = control.snapshot(home)
        self.assertEqual(facts['status'], 'Running')
        self.assertEqual(facts['menu_delivery'], 'failed')
        self.assertNotIn('secret', json.dumps(facts))
        rows = module('desktop_model').menu(facts)['menu']
        self.assertTrue(any('Menu update needs repair' in row['label'] for row in rows))
