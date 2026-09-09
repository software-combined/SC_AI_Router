"""Plan 049 Claude attach: two-key merge, conflict refusal, receipt record.

Synthetic settings only; never touches the operator's real settings.json.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.test_install import install_mod

claude_config = install_mod._claude_config


def _state():
    return {'port': 1, 'token': 'test-token', 'openai_models': [],
            'claude_mode': 'subscription'}


class ClaudeMergeTests(unittest.TestCase):
    def test_merge_adds_only_the_two_owned_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'model': 'keep-me', 'env': {'OTHER': '1'}}))
            doc, changed, previous = claude_config.merge_env(Path(tmp), _state(), path)
            self.assertTrue(changed)
            self.assertEqual(doc['model'], 'keep-me')
            self.assertEqual(doc['env']['OTHER'], '1')
            self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
            self.assertEqual(doc['env']['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], 'true')
            self.assertEqual(previous, {'ANTHROPIC_BASE_URL': None,
                                        'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': None})

    def test_rerun_is_stable_and_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            doc, _, _ = claude_config.merge_env(Path(tmp), _state(), path)
            claude_config.write_settings(path, doc)
            doc2, changed2, _ = claude_config.merge_env(Path(tmp), _state(), path)
            self.assertFalse(changed2)
            self.assertEqual(doc2, doc)
            self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')

    def test_conflicting_override_refuses_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://other.example'}}))
            with self.assertRaisesRegex(SystemExit, 'managed outside'):
                claude_config.merge_env(Path(tmp), _state(), path)
            self.assertNotIn('127.0.0.1', path.read_text())

    def test_detach_restores_hand_kept_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {}}))
            install_mod.attach_claude(home, _state(), settings_path=path)
            doc = json.loads(path.read_text())
            doc['env']['ANTHROPIC_BASE_URL'] = 'https://keep.example'
            path.write_text(json.dumps(doc))
            install_mod.detach_claude(home, settings_path=path)
            # Detach restores the attach-time value, not the hand edit:
            # the receipt owns the prior state, concurrent edits are
            # refused at attach time by merge_env.
            doc = json.loads(path.read_text())
            self.assertNotIn('127.0.0.1', doc['env'].get('ANTHROPIC_BASE_URL', ''))

    def test_attach_and_detach_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {}}))
            out = install_mod.attach_claude(home, _state(), settings_path=path)
            self.assertEqual(out, path)
            doc = json.loads(path.read_text())
            self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertIn('claude', receipt['clients'])
            install_mod.detach_claude(home, settings_path=path)
            doc = json.loads(path.read_text())
            self.assertNotIn('ANTHROPIC_BASE_URL', doc['env'])
            # Last attachment out removes the receipt itself.
            self.assertFalse((home / 'activation.json').exists())

    def test_settings_path_honors_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {'CLAUDE_CONFIG_DIR': tmp}
            self.assertEqual(claude_config.settings_path(env),
                             Path(tmp) / 'settings.json')
            self.assertEqual(claude_config.settings_path({}),
                             Path.home() / '.claude' / 'settings.json')
            self.assertNotIn('test-token', os.environ.get('CLAUDE_CONFIG_DIR', ''))


    def test_default_path_resolves_through_config_dir(self):
        # The real installer path passes no settings_path: resolution must
        # go through CLAUDE_CONFIG_DIR, not crash on a shadowed name.
        import tempfile as _tf
        from unittest import mock as _mock
        home = Path(_tf.mkdtemp())
        cfgdir = Path(_tf.mkdtemp())
        with _mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfgdir)}):
            out = install_mod.attach_claude(home, _state())
        self.assertEqual(out, cfgdir / 'settings.json')
        doc = json.loads(out.read_text())
        self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
        with _mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfgdir)}):
            install_mod.detach_claude(home)
        doc = json.loads(out.read_text())
        self.assertNotIn('ANTHROPIC_BASE_URL', doc.get('env', {}))

    def test_uninstall_detaches_claude_only_attachment(self):
        # Plan 049: uninstall with only a Claude attachment restores its
        # settings instead of taking the service-only early return.
        import tempfile as _tf
        from unittest import mock as _mock
        from tests.test_install_config import _install
        with _tf.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            cfgdir = Path(tmp) / 'claudedir'
            cfgdir.mkdir()
            with _mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfgdir)}):
                _install(self, tmp, home, '1.0.0', '--clients', 'claude')
                settings = cfgdir / 'settings.json'
                self.assertIn('ANTHROPIC_BASE_URL',
                              json.loads(settings.read_text())['env'])
                args = install_mod.build_parser().parse_args(
                    ['--home', str(home), '--uninstall'])
                from tests.test_install import _patch_attrs as _pa, _ok_run
                _pa(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
                with _mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome'),
                                                   'OPENROUTER_API_KEY': 'k'}):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
                doc = json.loads(settings.read_text())
                self.assertNotIn('ANTHROPIC_BASE_URL', doc.get('env', {}))

if __name__ == '__main__':
    unittest.main()
