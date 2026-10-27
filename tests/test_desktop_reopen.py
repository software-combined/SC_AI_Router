"""Reopening controls reveals the Mac menu without repeating an action window."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module

HELPER = 'scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu'


class DesktopReopenTests(unittest.TestCase):
    def test_reopening_mac_requests_the_existing_menu_instead_of_a_second_window(self):
        menu = module('desktop_menu')
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(menu.sys, 'platform', 'darwin'):
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / HELPER).touch()
            (home / 'installer.json').write_text('{"version":"1.3.7"}')
            request = home / (menu.session_lock() + '.open')
            observed = []
            def consume(_):
                observed.append(request.is_file())
                request.unlink()
            with menu.load('service').install_lock(home, menu.session_lock()), \
                    mock.patch.object(menu.time, 'sleep', side_effect=consume), \
                    mock.patch.object(menu, 'fallback') as fallback:
                self.assertEqual(menu.run_menu(home, home), 0)
                fallback.assert_not_called()
                self.assertEqual(observed, [True])
                self.assertEqual(menu.run_menu(home, home, autostart=True), 0)
                self.assertFalse(request.exists(), 'sign-in launches must stay quiet')

    def test_running_mac_menu_consumes_one_reopen_request(self):
        menu, documents, events_queue = module('desktop_menu'), [], []
        class Input(io.StringIO):
            def write(self, text):
                doc = json.loads(text)
                documents.append(doc)
                if doc.get('open_menu'):
                    events_queue[0].put({'closed': True})
                return len(text)
        shell = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), poll=lambda: None,
                                wait=lambda **kwargs: 0)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(menu.sys, 'platform', 'darwin'):
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / HELPER).touch()
            (home / 'installer.json').write_text('{"version":"1.3.7"}')
            request = home / (menu.session_lock() + '.open')
            request.touch()  # Preserve a request made before a resident controller hands off.
            def events(stream, queue):
                events_queue.append(queue)
                queue.put({'action': 'refresh'})
                # The old implementation ignores the request; end it without hanging.
                queue.put({'closed': True})
            with mock.patch.object(menu, '_events', side_effect=events), \
                    mock.patch.object(menu, '_control', return_value=dict(status='Running', clients=[])), \
                    mock.patch.object(menu.subprocess, 'Popen', return_value=shell):
                self.assertEqual(menu.run_menu(home, home, autostart=True), 74)
            self.assertEqual(sum(bool(doc.get('open_menu')) for doc in documents), 1)
            self.assertFalse(request.exists())

    def test_a_stale_reopen_request_does_not_open_the_menu_at_sign_in(self):
        menu, documents = module('desktop_menu'), []
        class Input(io.StringIO):
            def write(self, text):
                documents.append(json.loads(text))
                return len(text)
        shell = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), poll=lambda: None,
                                wait=lambda **kwargs: 0)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(menu.sys, 'platform', 'darwin'):
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / HELPER).touch()
            (home / 'installer.json').write_text('{"version":"1.3.7"}')
            request = home / (menu.session_lock() + '.open')
            request.touch()
            with mock.patch.object(menu.time, 'time', return_value=request.stat().st_mtime + 10), \
                    mock.patch.object(menu, '_events', side_effect=lambda stream, queue: queue.put({'closed': True})), \
                    mock.patch.object(menu, '_control', return_value=dict(status='Running', clients=[])), \
                    mock.patch.object(menu.subprocess, 'Popen', return_value=shell):
                self.assertEqual(menu.run_menu(home, home, autostart=True), 74)
            self.assertFalse(any(doc.get('open_menu') for doc in documents))
            self.assertFalse(request.exists())

    def test_new_controller_keeps_controls_available_with_an_older_mac_helper(self):
        menu = module('desktop_menu')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / HELPER).touch()
            (home / 'installer.json').write_text('{"version":"1.3.6.191"}')
            with mock.patch.object(menu.sys, 'platform', 'darwin'), \
                    mock.patch.object(menu, 'fallback') as fallback, \
                    mock.patch.object(menu.subprocess, 'Popen') as launch:
                self.assertEqual(menu.run_menu(home, home), 0)
                fallback.assert_called_once_with(home, home)
                launch.assert_not_called()
                self.assertFalse((home / (menu.session_lock() + '.open')).exists())

    def test_an_older_running_controller_gets_a_bounded_fallback_without_a_stale_request(self):
        menu, elapsed = module('desktop_menu'), [0]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'control').mkdir()
            (home / 'control' / HELPER).touch()
            (home / 'installer.json').write_text('{"version":"1.3.7"}')
            with mock.patch.object(menu.sys, 'platform', 'darwin'), \
                    menu.load('service').install_lock(home, menu.session_lock()), \
                    mock.patch.object(menu.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                    mock.patch.object(menu.time, 'sleep', side_effect=lambda delay: elapsed.__setitem__(0, elapsed[0] + delay)), \
                    mock.patch.object(menu, 'fallback') as fallback:
                self.assertEqual(menu.run_menu(home, home), 0)
                fallback.assert_called_once_with(home, home)
                self.assertLess(elapsed[0], 2.2)
                self.assertFalse((home / (menu.session_lock() + '.open')).exists())

    def test_control_window_runs_one_action_then_shows_its_result_and_closes(self):
        menu, dialog, control, model = (module('desktop_menu'), mock.Mock(),
                                       mock.Mock(), module('desktop_model'))
        control.snapshot.return_value = dict(status='Running', clients=[])
        dialog.choose.side_effect = ['router.restart', None]
        owners = dict(desktop_model=model, desktop_control=control, native_dialog=dialog,
                      native_shortcuts=module('native_shortcuts'), service=module('service'),
                      windows_native=module('windows_native'))
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(menu, 'load', side_effect=owners.__getitem__), \
                mock.patch.object(menu, '_control', return_value={'outcome': 'done'}) as execute:
            self.assertEqual(menu.fallback(Path(temporary), Path('/resources')), {'outcome': 'done'})
        dialog.choose.assert_called_once()
        self.assertEqual(dialog.choose.call_args.kwargs['labels'], ('Run action', 'Close'))
        execute.assert_called_once()
        dialog.message.assert_called_once_with('Restart Router completed.')

    def test_control_window_buttons_keep_a_safe_close_action_on_every_platform(self):
        dialog = module('client_dialog')
        for platform, tool in (('darwin', 'osascript'), ('win32', 'powershell'), ('linux', 'zenity')):
            command = dialog.argv(tool, platform, 'Choose an action.', [('test', 'Long connection label')],
                                  labels=('Run action', 'Close'))
            text = ' '.join(command)
            self.assertIn('Run action', text)
            self.assertIn('Close', text)
            self.assertNotIn('Continue', text)
            if platform == 'darwin':
                self.assertIn('picker.sizeToFit', text)
            if platform == 'win32':
                self.assertIn('TextRenderer]::MeasureText', text)
                self.assertIn('$b.HorizontalScrollbar = $true', text)
                self.assertIn("$f.AutoSizeMode = 'GrowAndShrink'", text)
                self.assertIn('$f.AutoSize = $true', text)
                self.assertIn("$l.MaximumSize = '640,0'", text)

    def test_only_one_fallback_window_opens_per_session_on_every_platform(self):
        menu = module('desktop_menu')
        real_load = menu.load
        native = SimpleNamespace(Native=lambda: SimpleNamespace(session=lambda: 1))
        for platform in ('darwin', 'win32', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                with mock.patch.object(menu.sys, 'platform', platform), \
                        mock.patch.object(menu, 'load', side_effect=lambda name:
                            native if name == 'windows_native' else real_load(name)), \
                        menu.load('service').install_lock(home, menu.session_lock() + '.window'), \
                        mock.patch.object(menu, '_control_window') as window:
                    self.assertEqual(menu.fallback(home, home), {'outcome': 'done'})
                    window.assert_not_called()

    def test_closing_or_cancelling_a_control_action_never_reports_success(self):
        menu, dialog = module('desktop_menu'), mock.Mock()
        control = mock.Mock()
        control.snapshot.return_value = dict(status='Running', clients=[])
        owners = dict(desktop_model=module('desktop_model'), desktop_control=control,
                      native_dialog=dialog, native_shortcuts=module('native_shortcuts'))
        for action, result in ((None, {'outcome': 'done'}),
                               ('router.restart', {'outcome': 'cancelled'}),
                               ('router.restart', {'outcome': 'failed'})):
            with self.subTest(action=action, result=result), tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.object(menu, 'load', side_effect=owners.__getitem__), \
                    mock.patch.object(menu, '_control', return_value=result) as execute:
                dialog.choose.return_value = action
                self.assertEqual(menu._control_window(Path(temporary), Path('/resources')), result)
                self.assertEqual(execute.call_count, int(action is not None))
                dialog.message.assert_not_called()

    def test_setup_check_does_not_enter_the_wizard_without_finish_setup(self):
        setup, dialog, switch = module('native_setup'), mock.Mock(), mock.Mock()
        facts = dict(serving=True, update={}, onboarding=dict(ready=False, clients={'claude-desktop': {}}))
        dialog.confirm_result.return_value = False
        with mock.patch.object(setup, 'status', return_value=facts), \
                mock.patch.object(setup, '_claude_on_openrouter', switch):
            setup._check(Path('/resources'), Path('/home'), dialog)
        switch.assert_not_called()
        self.assertEqual(dialog.confirm_result.call_args.kwargs['labels'], ('Finish setup', 'Cancel'))
        facts['onboarding']['ready'] = True
        dialog.confirm_result.reset_mock()
        with mock.patch.object(setup, 'status', return_value=facts):
            setup._check(Path('/resources'), Path('/home'), dialog)
        dialog.confirm_result.assert_not_called()
        self.assertTrue(dialog.message.call_args.args[0].startswith('Ready.'))

    def test_every_shared_menu_action_is_supported_and_busy_menus_cannot_run_actions(self):
        model, control = module('desktop_model'), module('desktop_control')
        clients = [dict(id=name, label=name.title(), selected='subscription', choices=[
            dict(id='subscription', label='Subscription'), dict(id='openrouter', label='OpenRouter')])
            for name in ('codex', 'claude')]
        def leaves(rows):
            for row in rows:
                if row['children']:
                    yield from leaves(row['children'])
                elif row['action']:
                    yield row
        for status in ('Running', 'Needs attention', 'Router is not running'):
            for connected in ([], clients[:1], clients[1:], clients):
                facts = dict(status=status, clients=connected, version='1.3.7', running_version='1.3.6',
                             update=dict(required_action='update', latest_known_version='1.3.8'))
                for busy in (None, 'Switching…', 'Updating…', 'Working…'):
                    with self.subTest(status=status, clients=len(connected), busy=busy):
                        rows = model.menu(facts, busy=busy)['menu']
                        for row in leaves(rows):
                            self.assertIn(row['action'], (*control.ACTIONS, 'menu.quit'))
                            self.assertTrue(row['label'].strip())
                            if busy:
                                self.assertFalse(row['enabled'])
                        details, actions = model.chooser(rows)
                        self.assertEqual(len(actions), len(dict(actions)), 'one choice per action')
                        if busy:
                            self.assertEqual(actions, [])


if __name__ == '__main__':
    unittest.main()
