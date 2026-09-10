"""Setup-window starter choice: profile validation and install-once behavior."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_router import agents, setup
from tests.test_setup import NOW, _key_ok, _state


class SetupStarterTests(unittest.TestCase):
    def test_post_rejects_unknown_starter_choice(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=none&profile=bogus',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 422)
        self.assertFalse((home / 'openrouter.key').exists())

    def test_post_installs_dev_starter_once_and_keeps_existing(self):
        from ai_router import agents
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        with mock.patch.object(agents, 'target',
                               return_value=home / 'AGENTS.md'):
            status, body = setup.handle_setup(
                state, home, 'n' * 16, True, b'key=sk-test&mode=none&profile=dev',
                _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'Development starter installed', body)
        self.assertIn('small verified changes', (home / 'AGENTS.md').read_text())
        self.assertEqual(state.get('agents_profile'), 'dev')
        # A repeat run with the other profile leaves the owner's file alone.
        state2 = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state2))
        (home / 'openrouter.key').unlink()
        with mock.patch.object(agents, 'target',
                               return_value=home / 'AGENTS.md'):
            status, body = setup.handle_setup(
                state2, home, 'n' * 16, True,
                b'key=sk-test&mode=none&profile=general',
                _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'Existing instructions kept', body)
        self.assertIn('small verified changes', (home / 'AGENTS.md').read_text())

    def test_post_close_failure_reverts_starter_and_stays_500(self):
        from ai_router import agents
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        starter = home / 'AGENTS.md'
        with mock.patch.object(agents, 'target', return_value=starter), \
                mock.patch.object(setup, '_finish_setup', return_value=False):
            status, body = setup.handle_setup(
                state, home, 'n' * 16, True, b'key=sk-test&mode=none&profile=general',
                _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 500)
        text = body.decode() if isinstance(body, bytes) else body
        self.assertIn('delete the key file', text)
        self.assertFalse(starter.exists())

    def test_starter_choice_is_persisted(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        with mock.patch.object(agents, 'target',
                               return_value=home / 'AGENTS.md'):
            status, _ = setup.handle_setup(
                state, home, 'n' * 16, True, b'key=sk-test&mode=none&profile=dev',
                _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        saved = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(saved.get('agents_profile'), 'dev')


if __name__ == '__main__':
    unittest.main()
