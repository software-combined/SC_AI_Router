"""Plan 073 desktop attach: four-key merge, conflict refusal, receipt record.

Synthetic profile directories only; never touches the operator's real
Claude-3p profile.
"""
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests._platform import unix_only
from tests.test_install import install_mod

desktop_config = install_mod._desktop_config


def _state():
    return {'port': 1, 'token': 'test-token', 'openai_models': [],
            'claude_mode': 'subscription'}


def _profile(tmp, entry=None, mode=None):
    data_dir = Path(tmp) / 'Claude-3p'
    (data_dir / 'configLibrary').mkdir(parents=True)
    (data_dir / 'configLibrary' / '_meta.json').write_text(json.dumps(
        {'appliedId': 'abc', 'entries': [{'id': 'abc', 'name': 'Default'}]}))
    (data_dir / 'configLibrary' / 'abc.json').write_text(
        json.dumps(entry if entry is not None else {}))
    if mode is not None:
        (data_dir / 'claude_desktop_config.json').write_text(
            json.dumps({'deploymentMode': mode}))
    return data_dir


def _entry(data_dir):
    return json.loads((data_dir / 'configLibrary' / 'abc.json').read_text())


class DesktopMergeTests(unittest.TestCase):
    def test_merge_adds_only_the_four_owned_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _profile(tmp, {'keep': 'me'})
            doc, changed, previous = desktop_config.merge_entry(
                _state(), data_dir / 'configLibrary' / 'abc.json')
            self.assertTrue(changed)
            self.assertEqual(doc['keep'], 'me')
            self.assertEqual(doc['inferenceProvider'], 'gateway')
            self.assertEqual(doc['inferenceCredentialKind'], 'static')
            self.assertIn('127.0.0.1:1/test-token', doc['inferenceGatewayBaseUrl'])
            self.assertTrue(doc['inferenceGatewayApiKey'])
            self.assertEqual(previous, {k: None for k in desktop_config.OWNED_KEYS})

    @unix_only
    def test_rerun_is_stable_and_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _profile(tmp)
            path = data_dir / 'configLibrary' / 'abc.json'
            doc, _, _ = desktop_config.merge_entry(_state(), path)
            desktop_config.write_json(path, doc)
            doc2, changed2, _ = desktop_config.merge_entry(_state(), path)
            self.assertFalse(changed2)
            self.assertEqual(doc2, doc)
            self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')

    def test_conflicting_override_refuses_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _profile(tmp, {'inferenceProvider': 'other'})
            with self.assertRaisesRegex(SystemExit, 'managed outside'):
                desktop_config.merge_entry(
                    _state(), data_dir / 'configLibrary' / 'abc.json')
            self.assertNotIn('127.0.0.1', (data_dir / 'configLibrary' / 'abc.json').read_text())

    def test_conflicting_mode_refuses_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp, mode='1p')
            with self.assertRaisesRegex(SystemExit, 'deploymentMode'):
                desktop_config.attach(home, _state(), install_mod._codex_config, data_dir_override=data_dir)
            self.assertNotIn('127.0.0.1', (data_dir / 'configLibrary' / 'abc.json').read_text())

    def test_missing_library_metadata_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            with self.assertRaisesRegex(SystemExit, 'library metadata'):
                desktop_config.attach(home, _state(), install_mod._codex_config,
                                      data_dir_override=Path(tmp) / 'empty')

    def test_detach_restores_hand_kept_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            desktop_config.attach(home, _state(), install_mod._codex_config, data_dir_override=data_dir)
            path = data_dir / 'configLibrary' / 'abc.json'
            doc = json.loads(path.read_text())
            doc['inferenceProvider'] = 'hand-edited'
            path.write_text(json.dumps(doc))
            desktop_config.detach(home, install_mod._codex_config, data_dir_override=data_dir)
            # Detach restores the attach-time value, not the hand edit:
            # the receipt owns the prior state, concurrent edits are
            # refused at attach time by merge_entry.
            self.assertNotIn('hand-edited', path.read_text())

    def test_attach_and_detach_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            out = desktop_config.attach(home, _state(), install_mod._codex_config, data_dir_override=data_dir)
            self.assertEqual(out, data_dir / 'configLibrary' / 'abc.json')
            self.assertIn('127.0.0.1:1/test-token',
                          _entry(data_dir)['inferenceGatewayBaseUrl'])
            self.assertEqual(
                json.loads((data_dir / 'claude_desktop_config.json').read_text()),
                {'deploymentMode': '3p'})
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertIn('claude-desktop', receipt['clients'])
            desktop_config.detach(home, install_mod._codex_config, data_dir_override=data_dir)
            self.assertEqual(_entry(data_dir), {})
            # Attach created the desktop config; detach removes it instead
            # of leaving an empty object the app never had.
            self.assertFalse((data_dir / 'claude_desktop_config.json').exists())
            # Last attachment out removes the receipt itself.
            self.assertFalse((home / 'activation.json').exists())

    def test_reattach_keeps_original_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            desktop_config.attach(home, _state(), install_mod._codex_config, data_dir_override=data_dir)
            desktop_config.attach(home, _state(), install_mod._codex_config, data_dir_override=data_dir)
            snapshot = json.loads(json.loads((home / 'activation.json').read_text())
                                  ['clients']['claude-desktop']['inserted_block'])
            self.assertEqual(snapshot['inferenceProvider'], None)
            desktop_config.detach(home, install_mod._codex_config, data_dir_override=data_dir)
            self.assertEqual(_entry(data_dir), {})

    def test_none_mode_refuses_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            state = dict(_state(), claude_mode='none')
            with self.assertRaisesRegex(SystemExit, 'claude_mode is none'):
                desktop_config.attach(home, state, install_mod._codex_config,
                                      data_dir_override=data_dir)
            self.assertEqual(_entry(data_dir), {})
            self.assertFalse((data_dir / 'claude_desktop_config.json').exists())

    def test_detach_without_claim_is_noop_without_profile(self):
        # CLI-only machines have no Claude-3p profile: installer teardown
        # must not fail resolving a path for an attachment that was never made.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            with mock.patch.dict(os.environ,
                                 {'CLAUDE_USER_DATA_DIR': str(Path(tmp) / 'no-such-profile')}):
                desktop_config.detach(home, install_mod._codex_config)
            self.assertFalse((home / 'activation.json').exists())

    def test_attach_preserves_prior_codex_entry(self):
        # Plan 095: the shared writer must not disturb other attachments;
        # the Codex entry survives a desktop attach byte-for-byte.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            receipts = install_mod._codex_config
            receipts.write_receipt(home, '/c/config.toml', 'block-codex',
                                   None, 'subscription', '')
            before = json.loads((home / 'activation.json').read_text())['clients']['codex']
            desktop_config.attach(home, _state(), receipts, data_dir_override=data_dir)
            doc = json.loads((home / 'activation.json').read_text())
            self.assertEqual(doc['version'], receipts.RECEIPT_VERSION)
            self.assertEqual(doc['clients']['codex'], before)
            self.assertIn('claude-desktop', doc['clients'])

    def test_data_dir_honors_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _profile(tmp)
            env = {'CLAUDE_USER_DATA_DIR': str(data_dir)}
            self.assertEqual(desktop_config.user_data_dir(env), data_dir)
            self.assertEqual(desktop_config.user_data_dir({}),
                             Path.home() / 'Library' / 'Application Support' / 'Claude-3p')

    def test_default_path_resolves_through_env(self):
        # The real installer path passes no data_dir: resolution must go
        # through CLAUDE_USER_DATA_DIR, not crash on a shadowed name.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(data_dir)}):
                out = desktop_config.attach(home, _state(), install_mod._codex_config)
            self.assertEqual(out, data_dir / 'configLibrary' / 'abc.json')
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(data_dir)}):
                desktop_config.detach(home, install_mod._codex_config)
            self.assertEqual(_entry(data_dir), {})


    def test_claimless_bare_detach_leaves_hand_set_cli_keys(self):
        # Correctness review: the uninstall-final sweep calls bare
        # detach_claude with no claude claim; hand-set CLI keys must survive.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            cfgdir = Path(tmp) / 'claudedir'
            cfgdir.mkdir()
            path = cfgdir / 'settings.json'
            path.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://hand.example'}}))
            with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfgdir)}):
                before = path.read_text()
                install_mod.detach_claude(home)
                self.assertEqual(path.read_text(), before)

    def test_override_detach_leaves_desktop_profile_untouched(self):
        # Scoped override path must not sweep the desktop profile.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            desktop_config.attach(home, _state(), install_mod._codex_config,
                                  data_dir_override=data_dir)
            before = (data_dir / 'configLibrary' / 'abc.json').read_text()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {}}))
            install_mod.detach_claude(home, settings_path=path)
            self.assertEqual((data_dir / 'configLibrary' / 'abc.json').read_text(), before)

    def test_extra_desktop_keys_survive_attach_and_detach(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp, {'keep': 'me', 'modelDiscoveryEnabled': True})
            (data_dir / 'claude_desktop_config.json').write_text(
                json.dumps({'deploymentMode': '3p', 'other': 1}))
            desktop_config.attach(home, _state(), install_mod._codex_config,
                                  data_dir_override=data_dir)
            self.assertEqual(_entry(data_dir)['keep'], 'me')
            desktop_config.detach(home, install_mod._codex_config,
                                  data_dir_override=data_dir)
            self.assertEqual(_entry(data_dir),
                             {'keep': 'me', 'modelDiscoveryEnabled': True})
            self.assertEqual(json.loads((data_dir / 'claude_desktop_config.json').read_text()),
                             {'deploymentMode': '3p', 'other': 1})

    @unix_only
    def test_uninstall_detaches_desktop_only_attachment(self):
        # Mirror of the CLI-only uninstall test: a desktop-only attachment
        # is restored instead of taking the service-only early return.
        from tests.test_install import _patch_attrs as _pa, _ok_run
        from tests.test_install_config import _install
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            data_dir = _profile(tmp)
            with mock.patch.dict(os.environ, {'CLAUDE_USER_DATA_DIR': str(data_dir)}):
                desktop_config.attach(home, _state(), install_mod._codex_config)
                self.assertIn('127.0.0.1', _entry(data_dir)['inferenceGatewayBaseUrl'])
                args = install_mod.build_parser().parse_args(
                    ['--home', str(home), '--uninstall'])
                _pa(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
                with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome'),
                                                   'OPENROUTER_API_KEY': 'k'}):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
                self.assertEqual(_entry(data_dir), {})
                self.assertFalse((home / 'activation.json').exists())


if __name__ == '__main__':
    unittest.main()
