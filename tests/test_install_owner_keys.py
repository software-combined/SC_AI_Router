"""Owner root keys stay the owner's; the managed block's keys stay unique.

The no-subscription block sets `model_provider` and friends at root. An owner
line setting the same root key would be a second definition that makes the
whole config unreadable to Codex, so attach drops it, records it, and detach
restores it. The same key inside an owner table is a different key and stays.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests._platform import unix_only
from tests.test_install_config import _install

_ROOT = Path(__file__).resolve().parents[1]
OWNER_ROOT = 'model_provider = "ollama"\napproval_policy = "never"\n'
OWNER = OWNER_ROOT + '[profiles.local]\nmodel_provider = "ollama"\n'


def _owner_config(tmp, text):
    path = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
    path.parent.mkdir(parents=True)
    path.write_text(text)


def _switch_module():
    spec = importlib.util.spec_from_file_location(
        'owner_keys_switch', _ROOT / 'packaging' / 'codex_switch_config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _detach(test, home):
    env = {**os.environ, 'ROUTER_HOME': str(home), 'ROUTER_RESTORE_ONLY': '1'}
    result = subprocess.run([sys.executable, str(_ROOT / 'tools' / 'disable.py')],
                            capture_output=True, text=True, env=env)
    test.assertEqual(result.returncode, 0, result.stderr)


@unix_only
class OwnerRootKeyTests(unittest.TestCase):
    def test_an_owner_provider_line_never_makes_the_config_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            _owner_config(tmp, OWNER)
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0', '--openai-mode', 'none')
            doc = tomllib.loads(config.read_text())
            self.assertEqual((doc['model_provider'], doc['approval_policy']),
                             ('scg_router', 'never'))
            self.assertEqual(doc['profiles']['local']['model_provider'], 'ollama')
            _detach(self, home)
            doc = tomllib.loads(config.read_text())
            self.assertEqual((doc['model_provider'], doc['approval_policy']),
                             ('ollama', 'never'))

    def test_an_update_from_the_table_shape_keeps_codex_readable(self):
        # Earlier none-mode blocks declared [model_providers.scg_router], which
        # swallowed the owner lines below them; the update brings those lines
        # back to root, so they must not become second definitions.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0', '--openai-mode', 'none')
            text = config.read_text()
            end = '# END local mixed model picker\n'
            new = text[text.index('# BEGIN'):text.index(end) + len(end)]
            old = (new.replace('model_providers.scg_router.name',
                               '[model_providers.scg_router]\nname', 1)
                   .replace('model_providers.scg_router.', ''))
            config.write_text(text.replace(new, old + OWNER_ROOT))
            receipt = home / 'activation.json'
            record = json.loads(receipt.read_text())
            record['clients']['codex']['inserted_block'] = old
            receipt.write_text(json.dumps(record))
            config, _, _, _ = _install(self, tmp, home, '1.0.1')
            doc = tomllib.loads(config.read_text())
            self.assertEqual((doc['model_provider'], doc['approval_policy']),
                             ('scg_router', 'never'))
            _detach(self, home)
            self.assertEqual(tomllib.loads(config.read_text())['model_provider'], 'ollama')

    def test_a_mode_flip_keeps_every_earlier_removed_line_for_detach(self):
        with tempfile.TemporaryDirectory() as tmp:
            _owner_config(tmp, 'approvals_reviewer = "auto_review"\n' + OWNER_ROOT)
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0')
            config, _, _, _ = _install(self, tmp, home, '1.0.1', '--openai-mode', 'none')
            tomllib.loads(config.read_text())
            _detach(self, home)
            doc = tomllib.loads(config.read_text())
            self.assertEqual((doc['approvals_reviewer'], doc['model_provider']),
                             ('auto_review', 'ollama'))

    def test_a_line_re_added_while_attached_comes_back_once(self):
        # The owner re-adds a key the block owns; the next update sets it aside
        # again, and detach must restore one definition, the latest.
        with tempfile.TemporaryDirectory() as tmp:
            _owner_config(tmp, OWNER_ROOT)
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0', '--openai-mode', 'none')
            config.write_text('model_provider = "lmstudio"\n' + config.read_text())
            _install(self, tmp, home, '1.0.1')
            _detach(self, home)
            text = config.read_text()
            self.assertEqual(text.count('model_provider'), 1)
            self.assertEqual(tomllib.loads(text)['model_provider'], 'lmstudio')

    def test_a_rolled_back_switch_gives_back_the_owner_lines_it_set_aside(self):
        switch = _switch_module()
        with tempfile.TemporaryDirectory() as tmp:
            _owner_config(tmp, OWNER_ROOT)
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            before = json.loads((home / 'activation.json').read_text())['clients']['codex']
            switch.switch(home, 'switched')
            switch.restore(home, before, 'switched')
            doc = tomllib.loads(config.read_text())
            self.assertEqual((doc['model_provider'], doc['approval_policy']),
                             ('ollama', 'never'))

    def test_switch_codex_keeps_every_removed_line_for_detach(self):
        switch = _switch_module()
        with tempfile.TemporaryDirectory() as tmp:
            _owner_config(tmp, 'approvals_reviewer = "auto_review"\n' + OWNER_ROOT)
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            switch.switch(home, 'switched')
            self.assertEqual(tomllib.loads(config.read_text())['model_provider'], 'scg_router')
            entry = json.loads((home / 'activation.json').read_text())['clients']['codex']
            self.assertEqual(sorted(entry['reviewer']['removed']),
                             ['approvals_reviewer = "auto_review"', 'model_provider = "ollama"'])


if __name__ == '__main__':
    unittest.main()
