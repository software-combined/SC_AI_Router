"""Desktop actions use existing owners; polling never exposes private setup."""
import io
import json
import os
import plistlib
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module, resources


class DesktopControlsTests(unittest.TestCase):
    def test_linux_sessions_remain_distinct_when_they_share_a_user_bus(self):
        menu = module('desktop_menu')
        with mock.patch.object(menu.sys, 'platform', 'linux'), \
                mock.patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1/bus',
                                             'XDG_SESSION_ID': 'first'}):
            first = menu.session_lock()
            self.assertEqual(menu.session_lock(), first)
            os.environ['XDG_SESSION_ID'] = 'second'
            self.assertNotEqual(menu.session_lock(), first)

    def test_snapshot_redacts_owner_status_and_keeps_health_separate(self):
        control = module('desktop_control')
        installer = mock.Mock()
        installer._diag._status_document.return_value = dict(
            serving=False, routing_healthy=True, version='1.3.0.7',
            running_version='1.3.0.6', clients={'codex': {'config_path': '/private'}},
            token='private-token', key='private-key', feed='/private')
        config = mock.Mock(SWITCHED='switched')
        config.current.return_value = 'switched'
        config._codex.codex_attachment.return_value = {'openai_mode': 'subscription'}
        modules = dict(install=installer, codex_switch_config=config, update_status=module('update_status'),
                       desktop_startup=SimpleNamespace(enabled=lambda home: False))
        with mock.patch.object(control, 'load', side_effect=modules.__getitem__):
            facts = control.snapshot(Path('/unused'))
        self.assertEqual(facts['clients'][0]['selected'], 'openrouter')
        self.assertEqual(facts['status'], 'Running')
        self.assertEqual(facts['running_version'], '1.3.0.6')
        self.assertNotIn('private', json.dumps(facts))
        self.assertNotIn('reply_seen', facts)

    def test_fixed_destinations_reach_the_switch_owner(self):
        control, owner = module('desktop_control'), mock.Mock()
        for action, target in (('codex.openrouter', 'switched'), ('codex.subscription', 'switched_back'),
                               ('claude.openrouter', '3p'), ('claude.subscription', '1p')):
            with mock.patch.object(control, 'load', return_value=owner):
                self.assertEqual(control.execute('/home', '/resources', action)['outcome'], 'done')
            self.assertEqual(owner.switch.call_args.kwargs['target'], target)
        owner.switch.return_value = None
        with mock.patch.object(control, 'load', return_value=owner):
            self.assertEqual(control.execute('/home', '/resources', 'codex.openrouter')['outcome'], 'cancelled')
            with self.assertRaises(ValueError):
                control.execute('/home', '/resources', 'run shell')

    def test_poll_errors_are_json_only_and_never_open_dialogs(self):
        control = module('desktop_control')
        with mock.patch.object(control, 'snapshot', side_effect=ValueError('private')), \
                mock.patch.object(control, 'load') as load, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(control.main(['--home', '/home', '--resources', '/resources']), 1)
        self.assertEqual(json.loads(out.getvalue())['status'], 'Needs attention')
        load.assert_not_called()

    def test_fallback_has_every_profile_and_management_action(self):
        model = module('desktop_model')
        facts = dict(clients=[dict(id='codex', label='Codex', selected='subscription', choices=[
            dict(id='subscription', label='ChatGPT + OpenRouter'),
            dict(id='openrouter', label='OpenRouter only')])])
        actions = dict(model.actions(model.menu(facts, available='1.3.1')['menu']))
        for action in ('codex.subscription', 'codex.openrouter', 'setup.add', 'setup.remove',
                       'router.restart', 'updates.install', 'help.support', 'startup.toggle'):
            self.assertIn(action, actions)
        self.assertEqual(model.actions(model.menu(facts, busy='Switching…')['menu']), [])
        self.assertNotIn('claude.subscription', actions)

    def test_menu_ignores_repeated_clicks_and_leaves_service_running(self):
        menu = module('desktop_menu')
        release = threading.Event()
        calls, documents = [], []
        class Input(io.StringIO):
            def write(self, text):
                documents.append(json.loads(text))
                return len(text)
            def close(self):
                release.set()
                super().close()
        shell = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), poll=lambda: None,
                                wait=lambda **kwargs: 0)
        def events(stream, queue):
            for event in ({'action': 'codex.openrouter'}, {'action': 'codex.openrouter'}, {'closed': True}):
                queue.put(event)
        def control(home, resources, action=None):
            if action:
                calls.append(action)
                release.wait(2)
                return dict(outcome='done')
            return dict(status='Running', clients=[])
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
            with mock.patch.object(menu, '_events', side_effect=events), \
                    mock.patch.object(menu, '_control', side_effect=control), \
                    mock.patch.object(menu.subprocess, 'Popen', return_value=shell):
                self.assertEqual(menu.run_menu(home, home), 0)
        self.assertEqual(calls, ['codex.openrouter'])
        self.assertTrue(any(doc['status'] == 'Switching…' for doc in documents))

    def test_restart_requires_a_completed_service_handover_before_health(self):
        restart = module('desktop_service')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'mixed-router-state.json').write_text('{}')
            service, backend = mock.Mock(), mock.Mock()
            service.find_python.return_value = '/python'
            service.current_release_dir.return_value = home / 'releases/1.3.0'
            backend.install.side_effect = lambda *args: self.assertFalse(service.wait_version.called)
            args = SimpleNamespace(home=home, python=None, dry_run=False)
            self.assertEqual(restart.restart(args, service, backend), 0)
            self.assertIsNone(backend.install.call_args.args[-1])
            backend.install.side_effect = SystemExit('shutdown failed')
            service.wait_version.reset_mock()
            with self.assertRaises(SystemExit):
                restart.restart(args, service, backend)
            service.wait_version.assert_not_called()


class StartupTests(unittest.TestCase):
    def test_opt_out_survives_repair_and_foreign_entries_survive_removal(self):
        startup = module('desktop_startup')
        for platform in ('darwin', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, home, user = resources(root / 'Resources'), root / 'home', root / 'user'
                home.mkdir()
                with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(user / '.config')}):
                    startup.configure(home, source, True, platform_name=platform, user_home=user)
                    target = (user / 'Library/LaunchAgents' / (startup.IDENTITY + '.plist') if platform == 'darwin'
                              else user / '.config/autostart' / (startup.IDENTITY + '.desktop'))
                    self.assertTrue(target.is_file())
                    with startup.load('service').install_lock(home):
                        startup.remove(home, platform_name=platform, user_home=user)
                        startup.configure(home, source, None, platform_name=platform, user_home=user)
                    self.assertFalse(startup.enabled(home))
                    self.assertFalse(target.exists())
                    foreign = plistlib.dumps({'SCGRouterHome': '/someone-else'}) if platform == 'darwin' else b'foreign'
                    target.write_bytes(foreign)
                    startup.remove(home, platform_name=platform, user_home=user)
                    self.assertEqual(target.read_bytes(), foreign)

    def test_startup_lock_refuses_a_concurrent_change_without_restoring_opt_in(self):
        startup = module('desktop_startup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home = resources(root / 'Resources'), root / 'home'
            home.mkdir()
            (home / 'desktop-preferences.json').write_text('{"autostart":false}')
            with startup.load('service').install_lock(home, '.desktop-startup.lock'):
                with self.assertRaisesRegex(ValueError, 'already changing'):
                    startup.configure(home, source, None, platform_name='darwin', user_home=root / 'user')
                with self.assertRaisesRegex(ValueError, 'already changing'):
                    startup.remove(home, platform_name='darwin', user_home=root / 'user')
            self.assertFalse(startup.enabled(home))
            with startup.load('service').install_lock(home):
                with self.assertRaisesRegex(RuntimeError, 'operation is in progress'):
                    module('desktop_control').execute(home, source, 'startup.toggle')
            self.assertFalse(startup.enabled(home))

    def test_windows_startup_is_owned_and_removes_only_the_owned_shortcut(self):
        startup = module('desktop_startup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home = resources(root / 'Resources'), root / 'home'
            home.mkdir()
            run = mock.Mock()
            with mock.patch.dict(os.environ, {'APPDATA': str(root / 'AppData')}):
                startup.configure(home, source, True, platform_name='win32', run=run)
                self.assertIn('$s.Description -ne', run.call_args.args[0][-1])
                self.assertIn('--autostart', run.call_args.args[0][-1])
                startup.configure(home, source, False, platform_name='win32', run=run)
                self.assertIn('Remove-Item -LiteralPath', run.call_args.args[0][-1])
            self.assertFalse(startup.enabled(home))
