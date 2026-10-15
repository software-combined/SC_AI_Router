"""A second profile must never replace the first profile's restore receipt."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_client_choice import _full_install, _home


class ClaudeAttachmentPathTests(unittest.TestCase):
    def test_changed_profile_is_refused_before_either_settings_or_receipt_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            first, second = Path(tmp) / 'A/settings.json', Path(tmp) / 'B/settings.json'
            second.parent.mkdir()
            second.write_text('{"owner": true}\n')
            install_mod.attach_claude(home, install_mod.ensure_state(home),
                                      settings_path=first, listing={})
            paths = (first, second, home / 'activation.json')
            before = [p.read_bytes() for p in paths]
            with self.assertRaisesRegex(SystemExit, 'detach.*first'):
                install_mod.attach_claude(home, install_mod.ensure_state(home),
                                          env={'CLAUDE_CONFIG_DIR': str(second.parent)}, listing={})
            self.assertEqual([p.read_bytes() for p in paths], before)

    def test_setup_without_original_config_dir_preserves_restore_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            first = Path(tmp) / 'A/settings.json'
            install_mod.attach_claude(home, install_mod.ensure_state(home),
                                      settings_path=first, listing={})
            before = (first.read_bytes(), (home / 'activation.json').read_bytes())
            with mock.patch.object(install_mod, 'platform_backend'):
                rc, out, fake_home, _ = _full_install(
                    self, tmp, home, '1.0.0', ['--setup'], extra_env={'CLAUDE_CONFIG_DIR': ''})
            self.assertEqual(rc, 0)
            self.assertIn('detach', out)
            self.assertFalse((fake_home / '.claude/settings.json').exists())
            self.assertEqual((first.read_bytes(), (home / 'activation.json').read_bytes()), before)

    @unittest.skipIf(os.name == 'nt', 'creating symlinks needs Windows privileges')
    def test_symlink_alias_cannot_retarget_the_owned_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            first, second, alias = (Path(tmp) / name for name in ('A', 'B', 'alias'))
            first.mkdir()
            second.mkdir()
            alias.symlink_to(first, target_is_directory=True)
            state = install_mod.ensure_state(home)
            install_mod.attach_claude(home, state, settings_path=alias / 'settings.json', listing={})
            receipt = (home / 'activation.json').read_bytes()
            self.assertEqual(json.loads(receipt)['clients']['claude']['config_path'],
                             str((first / 'settings.json').resolve()))
            alias.unlink()
            alias.symlink_to(second, target_is_directory=True)
            with self.assertRaisesRegex(SystemExit, 'detach.*first'):
                install_mod.attach_claude(home, state, settings_path=alias / 'settings.json', listing={})
            self.assertFalse((second / 'settings.json').exists())
            self.assertEqual((home / 'activation.json').read_bytes(), receipt)
