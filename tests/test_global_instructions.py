"""Global rules install once, survive updates, and preserve the owner's edits."""
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_router.catalogue import merge
from tests.test_install_config import _install
from tools.global_instructions import BLOCK, prepare, restore, write
from tools import global_instructions


def install_rules(home, previous=None):
    path, before, after, receipt = prepare(home, previous)
    write(path, before, after)
    return receipt


class GlobalInstructionsTests(unittest.TestCase):
    def test_fresh_install_update_and_uninstall_preserve_other_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / 'AGENTS.md'
            original = '# My rules\n\nNever deploy without asking.\n'
            path.write_text(original)
            receipt = install_rules(home)
            self.assertEqual(path.read_text(), BLOCK + original)
            path.write_text(path.read_text() + '\nNew user rule.\n')
            receipt = install_rules(home, receipt)
            self.assertEqual(path.read_text().count(BLOCK), 1)
            restore(receipt)
            self.assertEqual(path.read_text(), original + '\nNew user rule.\n')
            restore(receipt)
            self.assertEqual(path.read_text(), original + '\nNew user rule.\n')

    def test_nonempty_override_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'AGENTS.md').write_text('base\n')
            shared = home / 'shared.md'
            shared.write_text('override\n')
            override = home / 'AGENTS.override.md'
            override.symlink_to(shared)
            receipt = install_rules(home)
            self.assertTrue(override.is_symlink())
            self.assertEqual(shared.read_text(), BLOCK + 'override\n')
            self.assertEqual((home / 'AGENTS.md').read_text(), 'base\n')
            restore(receipt)
            self.assertEqual(shared.read_text(), 'override\n')

    def test_fresh_profile_and_interrupted_receipt_do_not_duplicate_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'new-profile'
            receipt = install_rules(home)
            self.assertEqual(install_rules(home), receipt)
            self.assertEqual((home / 'AGENTS.md').read_text(), BLOCK)
            restore(receipt)
            self.assertEqual((home / 'AGENTS.md').read_text(), '')

    def test_edited_block_or_changed_active_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            receipt = install_rules(home)
            path = home / 'AGENTS.md'
            edited = path.read_text().replace('When delegation', 'When I allow delegation')
            path.write_text(edited)
            for action in (lambda: prepare(home, receipt), lambda: restore(receipt)):
                with self.assertRaises(SystemExit):
                    action()
                self.assertEqual(path.read_text(), edited)
            (home / 'AGENTS.override.md').write_text('override\n')
            with self.assertRaises(SystemExit):
                prepare(home, receipt)

    def test_concurrent_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, before, after, _ = prepare(Path(tmp))
            path.write_text('concurrent edit\n')
            with self.assertRaises(SystemExit):
                write(path, before, after)
            self.assertEqual(path.read_text(), 'concurrent edit\n')

    def test_installer_wires_global_rules_once_outside_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            path = config.parent / 'AGENTS.md'
            self.assertEqual(path.read_text(), BLOCK)
            _install(self, tmp, home, '1.0.1')
            self.assertEqual(path.read_text(), BLOCK)
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertEqual(receipt['global_instructions']['path'], str(path.resolve()))
            for model in merge({'models': []})['models']:
                self.assertNotIn('## Subagents and tool discovery',
                                 model['model_messages']['instructions_template'])
            restore(receipt['global_instructions'])
            self.assertEqual(path.read_text(), '')

    def test_disable_removes_owned_rules_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            config.write_text(config.read_text() + '\n# user setting\n')
            rules = config.parent / 'AGENTS.md'
            rules.write_text(rules.read_text() + 'User instructions.\n')
            disable = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
            with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home)}), \
                    mock.patch.dict('sys.modules', {'global_instructions': global_instructions}), \
                    mock.patch('subprocess.run'):
                runpy.run_path(str(disable))
            self.assertEqual(config.read_text(), '\n\n# user setting\n')
            self.assertEqual(rules.read_text(), 'User instructions.\n')
