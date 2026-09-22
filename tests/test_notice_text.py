"""The restart dialog's wording and the models it names (AGENTS.md 4a).

Both packaging modules are loaded from `packaging/` the way the installer
surface loads them, so these checks pin the plain-language sentence, the cap
that matches the desktop notification, and the fallbacks that keep a stopped
router from holding up a dialog.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


text_mod = _load('router_notice_text', _ROOT / 'packaging' / 'notice_text.py')
notice_mod = _load('router_notice', _ROOT / 'packaging' / 'notice.py')


class _Reply:
    """Minimal urlopen stand-in: a context manager carrying a JSON body."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self, _limit):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MessageTests(unittest.TestCase):
    def test_names_the_added_models_as_a_bullet_list(self):
        self.assertEqual(
            text_mod.message('1.0.1', 'codex',
                             ['Z.ai: GLM 5.3 Flash', 'Xiaomi: MiMo V2.6 Flash']),
            'SCG Router was updated to 1.0.1.\nNew models:\n'
            '- Z.ai: GLM 5.3 Flash\n'
            '- Xiaomi: MiMo V2.6 Flash\n'
            'Quit and reopen Codex to use them.')

    def test_without_names_keeps_the_version_sentence(self):
        self.assertEqual(
            text_mod.message('1.0.1', 'codex'),
            'SCG Router was updated to 1.0.1. '
            'Quit and reopen Codex to use the new models.')

    def test_the_action_follows_the_attached_clients(self):
        for clients, action in (
                ('claude', 'Restart Claude Code'),
                ('both', 'Quit and reopen Codex and restart Claude Code'),
                ('none', 'Restart your AI client')):
            with self.subTest(clients):
                self.assertIn(action,
                              text_mod.message('1.0.1', clients, ['A: One']))
        self.assertEqual(text_mod.clients('bogus'), 'codex')

    def test_dialog_command_carries_the_names(self):
        cmd = notice_mod.dialog_command(
            '1.0.1', platform_name='darwin',
            which=lambda name: '/usr/bin/' + name,
            names=['Z.ai: GLM 5.3 Flash', '+2 more'])
        script = cmd[cmd.index('-e') + 1]
        self.assertIn('New models:\\n- Z.ai: GLM 5.3 Flash\\n- +2 more', script)


class PendingNamesTests(unittest.TestCase):
    def _home(self, tmp, state):
        home = Path(tmp) / 'home'
        home.mkdir()
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        return home

    def test_names_come_from_the_router_and_cap(self):
        rows = [{'slug': 's/%d' % i, 'name': 'Model %d' % i} for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, {'port': 18749, 'token': 'tok'})
            names = text_mod.pending_names(
                home, _urlopen=lambda url, timeout: _Reply({'pending': rows}))
        self.assertEqual(names, ['Model 0', 'Model 1', 'Model 2', '+2 more'])

    def test_names_fall_back_when_the_router_is_unreachable(self):
        def boom(url, timeout):
            raise OSError('connection refused')

        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, {'port': 18749, 'token': 'tok'})
            self.assertEqual(text_mod.pending_names(home, _urlopen=boom), [])

    def test_names_need_a_usable_state(self):
        for state in ({}, {'port': '18749', 'token': 'tok'},
                      {'port': 18749, 'token': ''}):
            with tempfile.TemporaryDirectory() as tmp:
                home = self._home(tmp, state)
                self.assertEqual(text_mod.pending_names(home), [])

    def test_names_fall_back_on_a_malformed_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, {'port': 18749, 'token': 'tok'})
            self.assertEqual(
                text_mod.pending_names(
                    home,
                    _urlopen=lambda url, timeout: _Reply({'pending': 'x'})),
                [])


class DialogWiringTests(unittest.TestCase):
    def test_show_pending_hands_the_names_to_the_dialog(self):
        seen = {}

        def fake_dialog(version, **kwargs):
            seen.update(kwargs)
            return ['true']

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '1.0.1'}))
            with mock.patch.object(notice_mod, 'dialog_command',
                                   fake_dialog), \
                    mock.patch.object(notice_mod._text, 'pending_names',
                                      return_value=['Z.ai: GLM 5.3 Flash']), \
                    mock.patch.object(notice_mod, '_home_icon',
                                      return_value=''), \
                    mock.patch.object(notice_mod, '_dialog_up',
                                      return_value=True):
                shown = notice_mod.show_pending(
                    home, spawn=lambda cmd: 4242, pid_alive=lambda pid: True)
        self.assertTrue(shown)
        self.assertEqual(seen['names'], ['Z.ai: GLM 5.3 Flash'])
