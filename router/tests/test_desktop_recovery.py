"""A tray helper gets one retry; deliberate quit and startup choices persist."""
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module


class DesktopRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.menu = module('desktop_menu')
        self.args = ['--home', str(self.home), '--resources', str(self.home)]
        original = self.menu.load
        self.enterContext(mock.patch.object(self.menu, 'load', side_effect=lambda name:
            SimpleNamespace(environment=lambda _: {}) if name == 'native_setup' else original(name)))

    def test_unexpected_exit_retries_once_after_one_second(self):
        for answers, expected in (([74, 0], 0), ([74, 74], 74), ([0], 0)):
            with self.subTest(answers=answers), \
                    mock.patch.object(self.menu, 'run_menu', side_effect=answers) as run, \
                    mock.patch.object(self.menu.time, 'sleep') as sleep:
                self.assertEqual(self.menu.main(self.args), expected)
                self.assertEqual(run.call_count, len(answers))
                self.assertEqual(sleep.call_count, len(answers) - 1)
                if len(answers) == 2:
                    sleep.assert_called_once_with(1)

    def test_removal_and_resource_replacement_cancel_a_retry(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                def stopped(*_, **__):
                    if replacement:
                        (self.home / 'setup-current').write_text('new-resources')
                    else:
                        (self.home / '.router-removed').touch()
                    return 74
                with mock.patch.object(self.menu, 'run_menu', side_effect=stopped) as run, \
                        mock.patch.object(self.menu.time, 'sleep'), \
                        mock.patch.object(self.menu.os, 'execv') as reload:
                    self.menu.main(self.args)
                    run.assert_called_once()
                    self.assertEqual(reload.call_count, int(replacement))
                (self.home / '.router-removed').unlink(missing_ok=True)
                (self.home / 'setup-current').unlink(missing_ok=True)

    def test_startup_opt_out_skips_controller_and_exceptions_are_logged(self):
        (self.home / 'desktop-preferences.json').write_text('{"autostart":false}')
        with mock.patch.object(self.menu, 'run_menu') as run:
            self.assertEqual(self.menu.main(self.args + ['--autostart']), 0)
            run.assert_not_called()
        with mock.patch.object(self.menu, 'run_menu', side_effect=RuntimeError('/private/fixture')):
            self.assertEqual(self.menu.main(self.args), 1)
        text = (self.home / 'logs/maintenance.jsonl').read_text()
        self.assertIn('RuntimeError', text)
        self.assertNotIn('/private/fixture', text)

    def test_resource_reload_keeps_the_update_reason_after_startup_is_turned_off(self):
        preference = self.home / 'desktop-preferences.json'
        for flags in ([], ['--autostart'], ['--after-update']):
            with self.subTest(flags=flags):
                preference.write_text('{"autostart":true}')
                def advanced(*_, **__):
                    preference.write_text('{"autostart":false}')
                    return 75
                with mock.patch.object(self.menu, 'run_menu', side_effect=advanced), \
                        mock.patch.object(self.menu.os, 'execv') as reload:
                    self.assertEqual(self.menu.main(self.args + flags), 75)
                command = reload.call_args.args[1]
                self.assertEqual(command[-1], '--after-update')
                self.assertNotIn('--autostart', command)
                self.assertEqual(preference.read_text(), '{"autostart":false}')

    def test_helper_exit_code_is_logged_and_quit_is_not_retried(self):
        (self.home / 'control').mkdir()
        (self.home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        (self.home / 'installer.json').write_text('{"version":"1.3.7"}')
        shell = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                                poll=lambda: 37, wait=lambda **_: 37)
        with mock.patch.object(self.menu.subprocess, 'Popen', return_value=shell):
            self.assertEqual(self.menu.run_menu(self.home, self.home), 74)
        rows = [json.loads(line) for line in (self.home / 'logs/maintenance.jsonl').read_text().splitlines()]
        self.assertTrue(any(row.get('exit_code') == 37 for row in rows))
        shell = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                                poll=lambda: None, wait=lambda **_: 0)
        with mock.patch.object(self.menu.subprocess, 'Popen', return_value=shell), \
                mock.patch.object(self.menu, '_events', side_effect=lambda _, events:
                                  events.put({'action': 'menu.quit'})), \
                mock.patch.object(self.menu, '_control', return_value=dict(status='Running', clients=[])):
            self.assertEqual(self.menu.run_menu(self.home, self.home), 0)

    def test_startup_warning_waits_for_the_helper_and_first_menu_document(self):
        (self.home / 'control').mkdir()
        (self.home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        (self.home / 'installer.json').write_text('{"version":"1.3.7"}')
        shown, completed, sequence = threading.Event(), threading.Event(), []
        class Input(io.StringIO):
            def write(self, text):
                sequence.append('menu')
                shown.set()
                return len(text)
        shell = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), poll=lambda: None,
                                wait=lambda **_: 0)
        def offer(_):
            sequence.append('warning')
            self.assertTrue(shown.is_set())
            completed.set()
        def events(_, queue):
            completed.wait(3)
            queue.put({'closed': True})
        original = self.menu.load
        with mock.patch.object(self.menu, 'load', side_effect=lambda name:
                    SimpleNamespace(offer=offer) if name == 'update_warning' else original(name)), \
                mock.patch.object(self.menu, '_events', side_effect=events), \
                mock.patch.object(self.menu, '_control', return_value=dict(status='Running', clients=[])), \
                mock.patch.object(self.menu.subprocess, 'Popen', return_value=shell):
            self.assertEqual(self.menu.run_menu(self.home, self.home, autostart=True,
                                                offer_warning=True), 74)
        self.assertTrue(completed.is_set())
        self.assertLess(sequence.index('menu'), sequence.index('warning'))

    def test_existing_controller_never_starts_another_warning(self):
        (self.home / 'control').mkdir()
        (self.home / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')).touch()
        (self.home / 'installer.json').write_text('{"version":"1.3.7"}')
        original, offer = self.menu.load, mock.Mock()
        with self.menu.load('service').install_lock(self.home, self.menu.session_lock()), \
                mock.patch.object(self.menu, 'load', side_effect=lambda name:
                    SimpleNamespace(offer=offer) if name == 'update_warning' else original(name)):
            self.assertEqual(self.menu.main(self.args + ['--autostart']), 0)
        offer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
