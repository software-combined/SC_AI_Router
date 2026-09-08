"""Installer-generated state must satisfy the runtime loader (brief defect 1)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from codex_router.runtime import load_state
from tests.test_install import install_mod


class InstallStateTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        home = Path(tmp) / 'home'
        home.mkdir(parents=True)
        return home

    def _load(self, path):
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}):
            return load_state(path)

    def test_fresh_state_passes_runtime_load_with_default_roster(self):
        home = self._home()
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)
        self.assertEqual(len(state['openai_models']), 9)
        loaded = self._load(home / 'mixed-router-state.json')
        self.assertEqual(loaded['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)

    def test_existing_state_missing_roster_is_backfilled(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 't'}) + '\n')
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)
        self.assertEqual(self._load(home / 'mixed-router-state.json')['openai_models'],
                         install_mod.DEFAULT_OPENAI_MODELS)

    def test_existing_valid_state_is_untouched(self):
        home = self._home()
        before = json.dumps({'port': 1, 'token': 't', 'openai_models': ['x']}) + '\n'
        (home / 'mixed-router-state.json').write_text(before)
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], ['x'])
        self.assertEqual((home / 'mixed-router-state.json').read_text(), before)


if __name__ == '__main__':
    unittest.main()
