"""Repair must reuse a working key while first setup can still collect one."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module, resources


class NativeKeyPromptTests(unittest.TestCase):
    def test_repair_skips_the_key_window_when_the_saved_key_is_usable(self):
        self.check_prompt(usable=True)

    def test_setup_still_opens_the_key_window_without_a_usable_key(self):
        self.check_prompt(usable=False)

    def check_prompt(self, usable):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            home = root / 'home'
            home.mkdir()
            (home / 'current').write_text('1.2.0\n')
            key = home / 'openrouter.key'
            key.write_text('synthetic-saved-key' if usable else '')
            key.chmod(0o600)
            state = home / 'mixed-router-state.json'
            state.write_text(json.dumps(dict(clients='both', port=1, token='synthetic',
                                            setup=dict(nonce='test', expires=2000))))
            before = state.read_bytes()
            run = mock.Mock(return_value=SimpleNamespace(returncode=2))
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'synthetic-shell-key'}), \
                    mock.patch.object(setup.time, 'time', return_value=1000):
                setup._key(source, home, run=run)
            if usable:
                self.assertFalse(run.called, 'A usable saved key must skip the key window.')
            else:
                run.assert_called_once()
                self.assertIn('ai_router.key_prompt', run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs['env']['ROUTER_HOME'], str(home))
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(key.read_text(), 'synthetic-saved-key' if usable else '')
