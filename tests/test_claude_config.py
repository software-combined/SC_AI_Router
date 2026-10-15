"""Plan 112 Claude attach: two-key merge, conflict refusal, receipt record.

Synthetic settings only; never touches the operator's real settings.json.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only
from tests.install_fixtures import install_mod

claude_config = install_mod._claude_config


def _state():
    return {'port': 1, 'token': 'test-token', 'openai_models': [],
            'claude_mode': 'subscription'}


class ClaudeMergeTests(unittest.TestCase):
    def test_attach_records_the_served_listing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            listing = {'data': [
                {'id': 'z-ai/glm-5.3-flash',
                 'display_name': 'Z.ai: GLM 5.3 Flash · OpenRouter'},
                {'id': 'anthropic/claude-opus-5.5',
                 'display_name': 'Anthropic: Claude Opus 5.5 · OpenRouter',
                 'anthropic_family_tier': 'opus'}]}
            install_mod.attach_claude(home, _state(), settings_path=path,
                                      listing=listing)
            entry = install_mod._codex_config.read_receipt(home)['clients']['claude']
            snapshot = entry['listing']
            self.assertTrue(snapshot['served_at'].endswith('Z'))
            self.assertEqual([row['id'] for row in snapshot['models']],
                             ['z-ai/glm-5.3-flash', 'anthropic/claude-opus-5.5'])
            self.assertIsNone(snapshot['models'][0]['anthropic_family_tier'])

    def test_attach_without_a_listing_records_no_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            install_mod.attach_claude(home, _state(), settings_path=path)
            entry = install_mod._codex_config.read_receipt(home)['clients']['claude']
            self.assertNotIn('listing', entry)

    def test_reattach_keeps_the_snapshot_when_the_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            install_mod.attach_claude(home, _state(), settings_path=path,
                                      listing={'data': [{'id': 'a'}]})
            install_mod.attach_claude(home, _state(), settings_path=path,
                                      listing=None)
            entry = install_mod._codex_config.read_receipt(home)['clients']['claude']
            self.assertEqual([row['id'] for row in entry['listing']['models']], ['a'])

    def test_release_listing_is_best_effort(self):
        release = Path('/nonexistent/release')
        python = '/usr/bin/python3.14'

        def bombe(*args, **kwargs):
            raise OSError('runner unavailable')

        def probe(stdout='', returncode=0):
            return lambda *args, **kwargs: subprocess.CompletedProcess(
                [], returncode, stdout, '')

        self.assertIsNone(claude_config.release_listing(release, python, bombe))
        self.assertIsNone(claude_config.release_listing(release, python, probe('', 2)))
        self.assertIsNone(claude_config.release_listing(release, python, probe('not json')))
        self.assertIsNone(claude_config.release_listing(release, python, probe('[]')))
        self.assertIsNone(claude_config.release_listing(None, python, bombe))
        self.assertIsNone(claude_config.release_listing(release, None, bombe))
        self.assertEqual(
            claude_config.release_listing(release, python, probe('{"data": []}')),
            {'data': []})

    def test_attach_threads_the_resolved_interpreter_into_the_snapshot(self):
        # do_install resolves the 3.14 interpreter; the snapshot fetch must use
        # that same interpreter instead of re-discovering one.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            (home / 'releases' / '1.0.0' / 'packaging').mkdir(parents=True)
            (home / 'current').write_text('1.0.0\n')
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            seen = {}
            original = install_mod.run
            self.addCleanup(setattr, install_mod, 'run', original)

            def fake_run(cmd, **kwargs):
                seen['cmd'] = list(cmd)
                return subprocess.CompletedProcess(
                    cmd, 0, '{"data": [{"id": "served-model"}]}', '')

            install_mod.run = fake_run
            install_mod.attach_claude(home, _state(), settings_path=path,
                                      python='/opt/custom/python3.14')
            entry = install_mod._codex_config.read_receipt(home)['clients']['claude']
        self.assertEqual(seen['cmd'][:2], ['/opt/custom/python3.14', '-m'])
        self.assertEqual([row['id'] for row in entry['listing']['models']],
                         ['served-model'])

    def test_detach_drops_the_snapshot_with_the_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({}))
            install_mod.attach_claude(home, _state(), settings_path=path,
                                      listing={'data': [{'id': 'x'}]})
            install_mod.detach_claude(home, settings_path=path)
            clients = install_mod._codex_config.read_receipt(home).get('clients', {})
            self.assertNotIn('claude', clients)

    def test_listing_cli_prints_the_served_rows(self):
        # The installer's snapshot path runs exactly this command against the
        # installed release; it must stay read-only and offline.
        result = subprocess.run(
            [sys.executable, '-m', 'ai_router.claude', '--listing'],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.assertTrue(doc['data'])
        self.assertTrue({'id', 'display_name'} <= set(doc['data'][0]))

    def test_merge_adds_only_public_gateway_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'model': 'keep-me', 'env': {'OTHER': '1'}}))
            doc, changed, previous = claude_config.merge_env(Path(tmp), _state(), path)
            self.assertTrue(changed)
            self.assertEqual(doc['model'], 'keep-me')
            self.assertEqual(doc['env']['OTHER'], '1')
            self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
            self.assertEqual(doc['env']['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], 'true')
            self.assertEqual(doc['env']['ENABLE_TOOL_SEARCH'], 'true')
            self.assertNotIn('_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL', doc['env'])
            self.assertEqual(previous, {
                'ANTHROPIC_BASE_URL': None,
                'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': None,
                'ENABLE_TOOL_SEARCH': None})

    @unix_only
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
            self.assertEqual(out, path.resolve())
            doc = json.loads(path.read_text())
            self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertIn('claude', receipt['clients'])
            install_mod.detach_claude(home, settings_path=path)
            doc = json.loads(path.read_text())
            self.assertNotIn('ANTHROPIC_BASE_URL', doc['env'])
            # Last attachment out removes the receipt itself.
            self.assertFalse((home / 'activation.json').exists())

    def test_attach_preserves_prior_codex_entry(self):
        # Plan 095: the shared writer must not disturb other attachments;
        # the Codex entry survives a Claude attach byte-for-byte.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {}}))
            receipts = install_mod._codex_config
            receipts.write_receipt(home, '/c/config.toml', 'block-codex',
                                   None, 'subscription', '')
            before = json.loads((home / 'activation.json').read_text())['clients']['codex']
            install_mod.attach_claude(home, _state(), settings_path=path)
            doc = json.loads((home / 'activation.json').read_text())
            self.assertEqual(doc['version'], receipts.RECEIPT_VERSION)
            self.assertEqual(doc['clients']['codex'], before)
            self.assertIn('claude', doc['clients'])

    def test_fresh_home_attach_reads_back_versioned(self):
        # Plan 095: a Claude-only home must not produce a versionless file
        # that read_receipt rejects as never-attached.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'env': {}}))
            install_mod.attach_claude(home, _state(), settings_path=path)
            doc = install_mod._codex_config.read_receipt(home)
            self.assertEqual(doc['version'], install_mod._codex_config.RECEIPT_VERSION)
            self.assertIn('claude', doc['clients'])

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
            self.assertEqual(out, (cfgdir / 'settings.json').resolve())
        doc = json.loads(out.read_text())
        self.assertIn('127.0.0.1:1/test-token', doc['env']['ANTHROPIC_BASE_URL'])
        with _mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfgdir)}):
            install_mod.detach_claude(home)
        doc = json.loads(out.read_text())
        self.assertNotIn('ANTHROPIC_BASE_URL', doc.get('env', {}))

    @unix_only
    def test_uninstall_detaches_claude_only_attachment(self):
        # Plan 112: uninstall with only a Claude attachment restores its
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
                from tests.install_fixtures import _patch_attrs as _pa, _ok_run
                _pa(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
                with _mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome'),
                                                   'OPENROUTER_API_KEY': 'k'}):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
                doc = json.loads(settings.read_text())
                self.assertNotIn('ANTHROPIC_BASE_URL', doc.get('env', {}))

if __name__ == '__main__':
    unittest.main()
