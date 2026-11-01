"""Starters install once via the setup window and survive updates untouched."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from ai_router import agents
from ai_router.catalogue import merge
from tests.test_install_config import _install
from tools import global_instructions


@unix_only
class GlobalInstructionsTests(unittest.TestCase):
    def test_starter_installs_once_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(agents.install('general', home), 'general:' + str(home / 'AGENTS.md'))
            body = (home / 'AGENTS.md').read_text()
            self.assertIn('## Subagents and tool discovery', body)
            self.assertIn('This file is yours', body)
            # A second choice must not overwrite the owner's file.
            (home / 'AGENTS.md').write_text(body + '\nMy rule.\n')
            self.assertEqual(agents.install('dev', home), 'kept')
            self.assertIn('My rule.', (home / 'AGENTS.md').read_text())
            self.assertNotIn('verified changes', (home / 'AGENTS.md').read_text())

    def test_dev_and_general_templates_differ(self):
        general = agents.template('general')
        dev = agents.template('dev')
        self.assertIn('## Subagents and tool discovery', general)
        self.assertIn('## Subagents and tool discovery', dev)
        self.assertIn('small verified changes', dev)
        self.assertNotIn('small verified changes', general)
        self.assertEqual(agents.template('bogus'), general)
        for text in (general, dev):
            self.assertNotIn('KnowledgeVault', text)
            self.assertNotIn('Cyril', text)

    def test_nonempty_override_wins_and_empty_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'AGENTS.md').write_text('base\n')
            override = home / 'AGENTS.override.md'
            override.write_text('override\n')
            self.assertEqual(agents.target(home), override)
            self.assertEqual(agents.install('general', home), 'kept')
            self.assertEqual(override.read_text(), 'override\n')
            override.write_text('   \n')
            self.assertEqual(agents.target(home), home / 'AGENTS.md')
            self.assertEqual(agents.install('general', home), 'kept')
            self.assertEqual((home / 'AGENTS.md').read_text(), 'base\n')

    def test_revert_removes_only_an_untouched_starter(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = agents.install('general', home)
            self.assertTrue((home / 'AGENTS.md').exists())
            agents.revert(installed)
            self.assertFalse((home / 'AGENTS.md').exists())
            # An owner edit after install must survive a revert attempt.
            installed = agents.install('dev', home)
            (home / 'AGENTS.md').write_text(
                (home / 'AGENTS.md').read_text() + '\nOwner edit.\n')
            agents.revert(installed)
            self.assertIn('Owner edit.', (home / 'AGENTS.md').read_text())
            agents.revert('kept')
            agents.revert('bogus')
            self.assertIn('Owner edit.', (home / 'AGENTS.md').read_text())

    def test_install_skips_symlinks_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            real = home / 'real.md'
            real.write_text('')
            link = home / 'AGENTS.md'
            link.symlink_to(real)
            # A symlink target lives outside this contract: leave it alone.
            self.assertEqual(agents.install('general', home), 'kept')
            self.assertEqual(real.read_text(), '')
            dangling = home / 'AGENTS.override.md'
            dangling.symlink_to(home / 'missing.md')
            self.assertEqual(agents.target(home), home / 'AGENTS.md')
            self.assertEqual(agents.describe('skipped'),
                             'Starter not installed (setup continued)')
            fresh = home / 'fresh'
            fresh.mkdir()
            with mock.patch('os.open', side_effect=OSError('full')):
                self.assertEqual(agents.install('general', fresh), 'skipped')

    def test_legacy_shim_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / 'AGENTS.md'
            path.write_text('mine\n')
            got_path, before, after, receipt = global_instructions.prepare(home, {'path': 'x', 'block': 'y'})
            self.assertEqual(before, 'mine\n')
            self.assertEqual(after, 'mine\n')
            global_instructions.write(got_path, before, after + 'changed')
            self.assertEqual(path.read_text(), 'mine\n')
            global_instructions.restore(receipt)
            self.assertEqual(path.read_text(), 'mine\n')

    def test_installer_never_writes_global_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            self.assertFalse((config.parent / 'AGENTS.md').exists())
            (config.parent / 'AGENTS.md').write_text('owner\n')
            _install(self, tmp, home, '1.0.1')
            self.assertEqual((config.parent / 'AGENTS.md').read_text(), 'owner\n')
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertNotIn('global_instructions', receipt['clients']['codex'])
            for model in merge({'models': []})['models']:
                self.assertNotIn('## Subagents and tool discovery',
                                 model['model_messages']['instructions_template'])

    def test_disable_leaves_global_instructions_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            config.write_text(config.read_text() + '\n# user setting\n')
            rules = config.parent / 'AGENTS.md'
            rules.write_text('User instructions.\n')
            disable = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
            # Run it the way the installer does: subprocess with
            # ROUTER_RESTORE_ONLY=1. Never in-process (2026-09-13 incident).
            result = subprocess.run(
                [sys.executable, str(disable)], capture_output=True, text=True,
                env=dict(os.environ, ROUTER_HOME=str(home),
                         ROUTER_RESTORE_ONLY='1'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_text(), '\n\n# user setting\n')
            self.assertEqual(rules.read_text(), 'User instructions.\n')
