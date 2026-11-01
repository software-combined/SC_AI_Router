"""Without a Claude subscription: the key window, the menu and the Claude switch."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import key_dialog
from tests.install_fixtures import install_mod
from tests.test_claude_desktop_config import _profile, _state, desktop_config
from tests.test_claude_desktop_switch import switcher
from tests.test_native_setup import module, resources

receipts = install_mod._codex_config


class KeyWindowTests(unittest.TestCase):
    def setUp(self):
        self.setup = module('native_setup')
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = resources(root / 'download')
        self.home = root / 'home'
        self.home.mkdir()
        (self.home / 'current').write_text('1.2.0\n')
        self.state = self.home / 'mixed-router-state.json'
        self.installer = self.enterContext(mock.patch.object(
            self.setup, 'run_installer', return_value=SimpleNamespace(returncode=0, stdout='')))
        self.enterContext(mock.patch.object(self.setup.time, 'time', return_value=1000))
        self.enterContext(mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}))

    def window(self, clients, attached, answer=None):
        """Run the key window; `answer` is what the person chose for Claude."""
        self.state.write_text(json.dumps(dict(clients=clients, port=1, token='synthetic',
                                              setup=dict(nonce='test', expires=2000))))
        for name, mode in attached.items():
            receipts.write_client_receipt(self.home, name, {'claude_mode': mode})
        def saved(*_args, **_kwargs):
            if answer is not None:
                doc = json.loads(self.state.read_text())
                self.state.write_text(json.dumps(dict(doc, claude_mode=answer, anthropic_mode=answer)))
            return SimpleNamespace(returncode=0)
        run = mock.Mock(side_effect=saved)
        self.setup._key(self.source, self.home, run=run)
        argv = run.call_args.args[0]
        return argv[argv.index('--clients') + 1]

    def test_desktop_only_install_is_asked_about_a_claude_subscription(self):
        # Without the question, a desktop-only user can never record "No subscription".
        which = self.window('none', {'claude-desktop': 'subscription'})
        self.assertIn('claude_mode', [field for field, _, _ in key_dialog.questions(which)])
        self.installer.assert_not_called()  # the desktop reads the choice live

    def test_service_only_install_still_asks_only_for_the_key(self):
        self.assertEqual(key_dialog.questions(self.window('none', {})), [])

    def test_claude_code_is_set_up_again_only_when_the_answer_changed_its_mode(self):
        # Claude Code is attached before the window; a stale attachment keeps asking for a login.
        self.window('claude', {'claude': 'subscription'}, answer='none')
        self.installer.assert_called_once_with(self.source, self.home, ['--claude-mode', 'none'])
        for attached, answer in (({'claude': 'none'}, 'none'), ({'claude': 'subscription'}, None)):
            with self.subTest(attached=attached, answer=answer):
                self.installer.reset_mock()
                self.window('claude', attached, answer)
                self.installer.assert_not_called()


class MenuTests(unittest.TestCase):
    def test_subscription_choice_follows_the_saved_claude_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, path = Path(tmp), Path(tmp) / 'mixed-router-state.json'
            self.assertTrue(switcher.subscription_chosen(home))  # nothing saved yet
            for state, chosen in (({'anthropic_mode': 'none'}, False),
                                  ({'claude_mode': 'none'}, False),
                                  ({'anthropic_mode': 'subscription', 'claude_mode': 'none'}, True),
                                  ({'openai_mode': 'none'}, True)):  # legacy: unchanged
                with self.subTest(state=state):
                    path.write_text(json.dumps(state))
                    self.assertIs(switcher.subscription_chosen(home), chosen)

    def test_menu_greys_out_claude_subscription_without_one(self):
        control = module('desktop_control')
        installer = mock.Mock()
        installer._diag._status_document.return_value = dict(
            routing_healthy=True, clients={'claude-desktop': {}})
        owner = mock.Mock()
        owner.subscription_chosen.return_value = False
        owner.attached_profile.return_value = (None, {'deploymentMode': '3p'})
        modules = dict(install=installer, claude_desktop_switch=owner,
                       update_status=module('update_status'),
                       desktop_startup=SimpleNamespace(enabled=lambda home: False))
        with mock.patch.object(control, 'load', side_effect=modules.__getitem__):
            row, = control.snapshot(Path('/unused'))['clients']
        self.assertEqual({choice['id']: choice['enabled'] for choice in row['choices']},
                         {'subscription': False, 'openrouter': True})


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.home = self.root / 'router'
        self.home.mkdir()
        for lock in ('.claude-profile-switch.lock', 'install.lock'):
            (self.home / lock).touch(mode=0o600)
        profile = _profile(self.root, {})
        state = dict(_state(), claude_mode='none', anthropic_mode='none')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        desktop_config.attach(self.home, state, receipts, data_dir_override=profile)
        self.config = profile / 'claude_desktop_config.json'
        self.config.write_text(json.dumps({'deploymentMode': '3p'}))
        self.enterContext(mock.patch.object(switcher._platform, 'request_stop'))
        self.enterContext(mock.patch.object(switcher._platform, 'confirm'))

    def test_move_to_subscription_refuses_before_asking_or_quitting_claude(self):
        for target in ('1p', None):  # explicit choice, or the toggle from OpenRouter
            with self.subTest(target=target):
                with self.assertRaisesRegex(switcher.SwitchError, 'No Claude subscription'):
                    switcher.switch(self.home, run=mock.Mock(side_effect=AssertionError),
                                    target=target)
                switcher._platform.confirm.assert_not_called()
                switcher._platform.request_stop.assert_not_called()
                self.assertEqual(json.loads(self.config.read_text()), {'deploymentMode': '3p'})

    def test_first_move_to_openrouter_never_asks_for_a_subscription_task(self):
        # "Open a Code task in Claude" needs the subscription this person does not have.
        sync = mock.Mock(STORES=('tasks',))
        sync._records.record_paths.return_value = ['saved-task']
        roots = (self.root / 'Claude', self.root / 'Claude-3p')
        with mock.patch.object(switcher, '_initialized', return_value=False):
            with self.assertRaisesRegex(switcher.SwitchError, 'Open a Code task'):
                switcher._setup_only((sync, None, roots), '1p')
            self.assertTrue(switcher._setup_only((sync, None, roots), '1p', subscription=False))


if __name__ == '__main__':
    unittest.main()
