"""Startup defaults and quiet resource handoff are separate from a saved opt-out."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module, resources
from tests import test_native_resources as native_fixtures


class WindowsLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {'APPDATA': str(self.root / 'AppData')}))

    def test_invalid_windows_preferences_default_on_without_becoming_a_saved_choice(self):
        startup = module('desktop_startup')
        source = resources(self.root / 'Resources')
        preference = self.home / 'desktop-preferences.json'
        for value in (None, '{broken', '[]', '{}', '{"autostart":"false"}',
                      '{"autostart":true}', '{"autostart":false}'):
            with self.subTest(value=value):
                if value is None:
                    preference.unlink(missing_ok=True)
                else:
                    preference.write_text(value)
                self.assertEqual(startup.enabled(self.home, platform_name='win32'),
                                 value != '{"autostart":false}')
                before = preference.read_bytes() if preference.exists() else None
                startup.configure(self.home, source, None, platform_name='win32',
                                  user_home=self.root / 'user', run=mock.Mock())
                self.assertEqual(preference.read_bytes() if preference.exists() else None, before)
        with mock.patch.object(Path, 'read_text', side_effect=PermissionError('private path')):
            self.assertTrue(startup.enabled(self.home, platform_name='win32'))
            self.assertFalse(startup.enabled(self.home, platform_name='darwin'))

    def test_explicit_choice_is_saved_and_update_launch_bypasses_off_but_not_removal(self):
        startup, menu = module('desktop_startup'), module('desktop_menu')
        source = resources(self.root / 'Resources')
        startup.configure(self.home, source, False, platform_name='win32', run=mock.Mock())
        self.assertFalse(startup.enabled(self.home))
        (source / 'control').mkdir()
        (source / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        with mock.patch.object(menu.subprocess, 'Popen') as launch:
            menu.start(self.home, source, after_update=True)
            self.assertEqual(launch.call_args.args[0][-1], '--after-update')
            launch.reset_mock()
            menu.start(self.home, source, autostart=True)
            launch.assert_not_called()
            (self.home / '.router-removed').touch()
            menu.start(self.home, source, after_update=True)
            launch.assert_not_called()
        self.assertFalse(startup.enabled(self.home))

    def test_update_handoff_never_opens_a_chooser_or_warning_for_an_existing_controller(self):
        menu, service = module('desktop_menu'), module('service')
        (self.home / 'control').mkdir()
        (self.home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        warning = mock.Mock()
        original = menu.load
        with mock.patch.object(menu, 'load', side_effect=lambda name:
                SimpleNamespace(environment=lambda _: {}) if name == 'native_setup' else
                warning if name == 'update_warning' else original(name)), \
                service.install_lock(self.home, menu.session_lock()), \
                mock.patch.object(menu, 'fallback') as chooser, \
                mock.patch.object(menu.subprocess, 'Popen') as helper:
            self.assertEqual(menu.main(['--home', str(self.home), '--resources', str(self.home),
                                        '--after-update']), 0)
            chooser.assert_not_called()
            helper.assert_not_called()
            warning.offer.assert_not_called()
        rows = (self.home / 'logs/maintenance.jsonl').read_text()
        self.assertIn('existing_controller', rows)

    def test_resource_advance_launches_once_and_unchanged_or_removed_checks_do_not(self):
        owner, home, latest, data = native_fixtures.NativeResourcesTests().fixture(self.root / 'delivery')
        menu = mock.Mock()
        original = owner.load
        def install(home, permanent, python):
            (home / 'setup-current').write_text(permanent.name + '\n')
        with mock.patch.object(owner, 'load', side_effect=lambda name:
                menu if name == 'desktop_menu' else SimpleNamespace(install=install)
                if name == 'native_shortcuts' else original(name)):
            for _ in range(2):
                self.assertTrue(owner.deliver(home, latest, 'file:///latest.json', lambda _: data))
            menu.start.assert_called_once_with(home, owner.current(home), after_update=True)
            (home / '.router-removed').touch()
            menu.start.reset_mock()
            (home / 'desktop-delivery.json').unlink()
            self.assertFalse(owner.deliver(home, latest, 'file:///latest.json', lambda _: data))
            menu.start.assert_not_called()

    def test_update_launch_failure_records_only_safe_facts(self):
        menu = module('desktop_menu')
        (self.home / 'desktop_launch.py').touch()
        (self.home / 'control').mkdir()
        (self.home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        with mock.patch.object(menu.subprocess, 'Popen', side_effect=OSError('private path')):
            menu.start(self.home, self.home, after_update=True)
        rows = [json.loads(line) for line in (self.home / 'logs/maintenance.jsonl').read_text().splitlines()]
        self.assertTrue(any(row.get('reason') == 'launch_failed' for row in rows))
        self.assertNotIn('private path', json.dumps(rows))
