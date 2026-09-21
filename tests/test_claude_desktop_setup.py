"""Desktop attachment works without a new router release or manual setup."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.install_fixtures import install_mod


class DesktopSetupTests(unittest.TestCase):
    def test_current_install_attaches_desktop_without_reinstalling(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            (home / 'releases/1.0.0').mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            state = {'port': 1, 'token': 'test-token', 'claude_mode': 'subscription'}
            (home / 'mixed-router-state.json').write_text(json.dumps(state))
            profile = Path(tmp) / 'Claude-3p'
            args = install_mod.build_parser().parse_args([
                '--home', str(home), '--feed', 'file:///latest.json', '--desktop'])
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                    mock.patch.object(install_mod, 'install_bundle') as bundle, \
                    contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
            bundle.assert_not_called()
            self.assertEqual((home / 'current').read_text(), '1.0.0')
            entry = install_mod._desktop_config.applied_entry_path(profile)
            self.assertEqual(json.loads(entry.read_text())['inferenceProvider'], 'gateway')
            self.assertIn('claude-desktop', install_mod._codex_config.read_receipt(home)['clients'])

    def test_current_desktop_dry_run_does_not_create_a_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            (home / 'releases/1.0.0').mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            profile = Path(tmp) / 'Claude-3p'
            args = install_mod.build_parser().parse_args([
                '--home', str(home), '--feed', 'file:///latest.json', '--desktop', '--dry-run'])
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                    mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                    contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
            self.assertFalse(profile.exists())
            self.assertFalse((home / 'activation.json').exists())

    def test_corrupt_library_metadata_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'Claude-3p'
            library = profile / 'configLibrary'
            library.mkdir(parents=True)
            meta = library / '_meta.json'
            meta.write_text('broken')
            state = {'port': 1, 'token': 'test-token'}
            with self.assertRaisesRegex(SystemExit, 'library metadata'):
                install_mod._desktop_config.attach(Path(tmp), state,
                    install_mod._codex_config, data_dir_override=profile)
            self.assertEqual(meta.read_text(), 'broken')

    def test_current_install_applies_explicit_claude_mode(self):
        for previous, selected in (('none', 'subscription'), ('subscription', 'none')):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                (home / 'releases/1.0.0').mkdir(parents=True)
                (home / 'current').write_text('1.0.0')
                state = {'port': 1, 'token': 'test-token', 'claude_mode': previous}
                settings = home / 'mixed-router-state.json'
                settings.write_text(json.dumps(state))
                profile = Path(tmp) / 'Claude-3p'
                args = install_mod.build_parser().parse_args([
                    '--home', str(home), '--desktop', '--claude-mode', selected])
                with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(profile)}), \
                        mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if selected == 'none':
                        with self.assertRaisesRegex(SystemExit, 'claude_mode is none'):
                            install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
                        self.assertFalse(profile.exists())
                    else:
                        install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
                        self.assertTrue(profile.exists())
                self.assertEqual(json.loads(settings.read_text())['claude_mode'], selected)

    def test_failed_initial_metadata_write_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            home.mkdir()
            profile = Path(tmp) / 'Claude-3p'
            desktop = install_mod._desktop_config
            state = {'port': 1, 'token': 'test-token'}
            write = desktop.write_json

            def fail_metadata(path, doc):
                if Path(path).name == '_meta.json':
                    raise OSError('synthetic write failure')
                write(path, doc)

            with mock.patch.object(desktop, 'write_json', side_effect=fail_metadata):
                with self.assertRaises(OSError):
                    desktop.attach(home, state, install_mod._codex_config,
                                   data_dir_override=profile)
            entry = desktop.attach(home, state, install_mod._codex_config,
                                   data_dir_override=profile)
            self.assertEqual(desktop.read_entry(entry)['inferenceProvider'], 'gateway')


if __name__ == '__main__':
    unittest.main()
