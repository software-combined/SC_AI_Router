"""The installer-side gates around the client chooser.

A bare re-run and an unattended run must never prompt, and a cancel must
attach nothing while detaching nothing.
"""
import contextlib
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_client_choice import _full_install, _home, _install, dialog


class ChooserGateTests(unittest.TestCase):
    def _args(self, *argv):
        return install_mod.build_parser().parse_args(['--home', '/tmp/router', *argv])

    def test_a_fresh_interactive_install_is_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            args = self._args()
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask', return_value=('claude', 'app')):
                self.assertTrue(install_mod._client_choice.maybe_ask(
                    args, home, tool_path='/usr/bin/osascript'))
            self.assertEqual((args.clients, args.desktop), ('none', True))

    def test_an_attached_install_is_not_asked_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            args = self._args()
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask') as asked:
                self.assertFalse(install_mod._client_choice.maybe_ask(
                    args, home, tool_path='/usr/bin/osascript', attached=True))
            asked.assert_not_called()
            self.assertIsNone(args.clients)

    def test_choose_clients_asks_an_attached_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            args = self._args('--choose-clients')
            with mock.patch.object(sys.stdin, 'isatty', return_value=False), \
                    mock.patch.object(dialog, 'ask', return_value=('chatgpt', 'both')):
                self.assertTrue(install_mod._client_choice.maybe_ask(
                    args, home, tool_path='/usr/bin/osascript'))
            self.assertEqual((args.clients, args.desktop), ('codex', False))

    def test_a_claude_only_install_counts_as_attached(self):
        # A Claude-only home already serves a client, so an interactive
        # install run must not ask again.
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            _install(tmp, home, ['--clients', 'claude'])
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask') as asked:
                code, out, _, _ = _full_install(self, tmp, home, '1.0.1', [])
            self.assertEqual(code, 0)
            asked.assert_not_called()
            self.assertNotIn('Which AI assistant', out)

    def test_explicit_flags_bypass_the_chooser(self):
        for argv in (('--clients', 'codex'), ('--clients', 'claude'), ('--desktop',),
                     ('--client', 'none')):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as tmp:
                home = _home(tmp)
                args = self._args(*argv)
                with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                        mock.patch.object(dialog, 'ask') as asked:
                    self.assertFalse(install_mod._client_choice.maybe_ask(
                        args, home, tool_path='/usr/bin/osascript'))
                asked.assert_not_called()

    def test_unattended_and_dry_runs_are_not_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            with mock.patch.object(dialog, 'ask') as asked:
                with mock.patch.object(sys.stdin, 'isatty', return_value=False):
                    self.assertFalse(install_mod._client_choice.maybe_ask(
                        self._args(), home, tool_path='/usr/bin/osascript'))
                with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                        mock.patch.dict(os.environ, {'ROUTER_NO_CLIENT_CHOOSER': '1'}):
                    self.assertFalse(install_mod._client_choice.maybe_ask(
                        self._args(), home, tool_path='/usr/bin/osascript'))
                with mock.patch.object(sys.stdin, 'isatty', return_value=True):
                    self.assertFalse(install_mod._client_choice.maybe_ask(
                        self._args('--dry-run'), home, tool_path='/usr/bin/osascript'))
            asked.assert_not_called()

    def test_no_dialog_tool_keeps_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            args = self._args()
            out = io.StringIO()
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'tool', return_value=None), \
                    contextlib.redirect_stdout(out):
                self.assertFalse(install_mod._client_choice.maybe_ask(args, home))
            self.assertIsNone(args.clients)
            self.assertIn('Setup will use Codex', out.getvalue())

    def test_cancel_on_a_fresh_install_attaches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask', return_value=dialog.CANCELLED):
                code, out, fake_home, claude = _full_install(self, tmp, home, '1.0.0', [])
            self.assertEqual(code, 0)
            self.assertIn('no client attached', out)
            self.assertFalse((fake_home / '.codex' / 'config.toml').exists())
            self.assertFalse((claude / 'settings.json').exists())
            self.assertFalse((home / 'activation.json').exists())
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertNotIn('clients', state)

    def test_cancel_leaves_an_attached_machine_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            _install(tmp, home, ['--clients', 'both'])
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            settings = Path(tmp) / 'claude' / 'settings.json'
            state_path = home / 'mixed-router-state.json'
            paths = (config, settings, home / 'activation.json', state_path)
            before = tuple(path.read_bytes() for path in paths)
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask', return_value=dialog.CANCELLED):
                code, out, _, _, _ = _install(tmp, home, ['--choose-clients'])
            self.assertEqual(code, 0)
            self.assertNotIn('connected', out)
            self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_choose_clients_opens_the_chooser_on_a_current_install(self):
        # A bare re-run returns before the client stage, so the explicit
        # --choose-clients request has to reach the chooser through do_install.
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            with mock.patch.object(sys.stdin, 'isatty', return_value=False), \
                    mock.patch.object(dialog, 'ask', return_value=('claude', 'terminal')):
                code, out, _, _, claude = _install(tmp, home, ['--choose-clients'])
            self.assertEqual(code, 0)
            env = json.loads((claude / 'settings.json').read_text())['env']
            self.assertEqual(env['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], 'true')
            self.assertIn('Claude Code connected', out)

    def test_choose_clients_without_a_dialog_attaches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            state_path = home / 'mixed-router-state.json'
            before = json.loads(state_path.read_text())
            with mock.patch.object(sys.stdin, 'isatty', return_value=False), \
                    mock.patch.object(dialog, 'tool', return_value=None):
                code, out, _, fake_home, claude = _install(tmp, home, ['--choose-clients'])
            self.assertEqual(code, 0)
            self.assertFalse((fake_home / '.codex' / 'config.toml').exists())
            self.assertFalse((claude / 'settings.json').exists())
            self.assertFalse((home / 'activation.json').exists())
            after = json.loads(state_path.read_text())
            self.assertEqual(after.get('clients'), before.get('clients'))
            self.assertIn('nothing was attached', out)

    def test_cancel_on_a_newer_release_keeps_existing_attachments(self):
        # The newer-version path used to detach on a service-only run; a
        # cancel must keep the Codex block and the Claude settings.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            _full_install(self, tmp, home, '1.0.0', ['--clients', 'both'])
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            settings = Path(tmp) / 'claude' / 'settings.json'
            paths = (config, settings, home / 'activation.json')
            before = tuple(path.read_bytes() for path in paths)
            with mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                    mock.patch.object(dialog, 'ask', return_value=dialog.CANCELLED):
                code, out, _, _ = _full_install(self, tmp, home, '1.0.1',
                                                ['--choose-clients'])
            self.assertEqual(code, 0)
            self.assertIn('no client attached', out)
            self.assertEqual(tuple(path.read_bytes() for path in paths), before)
